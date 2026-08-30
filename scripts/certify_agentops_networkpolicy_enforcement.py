#!/usr/bin/env python3
"""Certify AgentOps NetworkPolicy enforcement on a real Kubernetes CNI."""

from __future__ import annotations

import argparse
import json
import subprocess
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.platform_contracts import canonical_json_fingerprint

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "docs/reports/agentops_networkpolicy_enforcement_2026-08-30.json"
KNOWN_ENFORCING_CNI = ("cilium", "calico", "antrea", "kube-router")


class NetworkPolicyCertificationError(RuntimeError):
    """The disposable NetworkPolicy probe could not be completed."""


def _kubectl(
    *args: str,
    input_payload: str | None = None,
    timeout: float = 30,
) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["kubectl", *args],
            cwd=ROOT,
            input=input_payload,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return completed.returncode == 0, (completed.stdout or completed.stderr).strip()


def _kubectl_json(*args: str) -> tuple[bool, dict[str, Any] | None, str]:
    ok, output = _kubectl(*args)
    if not ok:
        return False, None, output
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        return False, None, f"kubectl returned invalid JSON: {exc}"
    if not isinstance(value, dict):
        return False, None, "kubectl returned a non-object JSON document"
    return True, value, ""


def detect_cni(resources: list[dict[str, Any]]) -> dict[str, Any]:
    """Identify a CNI known to enforce NetworkPolicy from pod/DaemonSet metadata."""

    fragments: list[str] = []
    for resource in resources:
        fragments.append(json.dumps(resource, ensure_ascii=True, sort_keys=True).lower())
    observed = "\n".join(fragments)
    for cni in KNOWN_ENFORCING_CNI:
        if cni in observed:
            return {
                "name": cni,
                "recognized": True,
                "enforcement_expected": True,
            }
    if "kindnet" in observed:
        return {
            "name": "kindnet",
            "recognized": True,
            "enforcement_expected": False,
            "reason": "kindnet does not enforce Kubernetes NetworkPolicy",
        }
    return {
        "name": "unknown",
        "recognized": False,
        "enforcement_expected": False,
        "reason": "no known NetworkPolicy-enforcing CNI was detected",
    }


def _probe_manifests(namespace: str) -> list[dict[str, Any]]:
    server_code = (
        "from http.server import BaseHTTPRequestHandler,HTTPServer\n"
        "class H(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
        " def log_message(self,*args): pass\n"
        "HTTPServer(('0.0.0.0',8080),H).serve_forever()"
    )
    return [
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "server", "namespace": namespace, "labels": {"role": "server"}},
            "spec": {
                "containers": [
                    {
                        "name": "server",
                        "image": "python:3.12-alpine",
                        "command": ["python", "-c", server_code],
                        "ports": [{"name": "http", "containerPort": 8080}],
                    }
                ]
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "server", "namespace": namespace},
            "spec": {"selector": {"role": "server"}, "ports": [{"port": 8080, "targetPort": 8080}]},
        },
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "allowed", "namespace": namespace, "labels": {"role": "allowed"}},
            "spec": {
                "containers": [
                    {
                        "name": "client",
                        "image": "curlimages/curl:8.10.1",
                        "command": ["sleep", "300"],
                    }
                ]
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "denied", "namespace": namespace, "labels": {"role": "denied"}},
            "spec": {
                "containers": [
                    {
                        "name": "client",
                        "image": "curlimages/curl:8.10.1",
                        "command": ["sleep", "300"],
                    }
                ]
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "server-ingress", "namespace": namespace},
            "spec": {
                "podSelector": {"matchLabels": {"role": "server"}},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [{"podSelector": {"matchLabels": {"role": "allowed"}}}],
                        "ports": [{"protocol": "TCP", "port": 8080}],
                    }
                ],
            },
        },
    ]


def _run_disposable_probe(
    *,
    kubectl: Callable[..., tuple[bool, str]],
    namespace: str,
) -> dict[str, bool]:
    manifests = json.dumps(
        {"apiVersion": "v1", "kind": "List", "items": _probe_manifests(namespace)}
    )
    checks: dict[str, bool] = {}
    created = False
    try:
        ok, detail = kubectl("create", "namespace", namespace)
        if not ok:
            raise NetworkPolicyCertificationError(f"namespace creation failed: {detail}")
        created = True
        ok, detail = kubectl("apply", "-f", "-", input_payload=manifests, timeout=60)
        if not ok:
            raise NetworkPolicyCertificationError(f"probe manifest apply failed: {detail}")
        for pod in ("server", "allowed", "denied"):
            ok, detail = kubectl(
                "wait",
                "--for=condition=Ready",
                f"pod/{pod}",
                "--namespace",
                namespace,
                "--timeout=120s",
                timeout=150,
            )
            if not ok:
                raise NetworkPolicyCertificationError(f"pod {pod} did not become ready: {detail}")
        ok, _ = kubectl(
            "exec",
            "--namespace",
            namespace,
            "allowed",
            "--",
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "5",
            "http://server:8080",
            timeout=15,
        )
        checks["allowed_ingress_reaches_server"] = ok
        denied_ok, _ = kubectl(
            "exec",
            "--namespace",
            namespace,
            "denied",
            "--",
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "5",
            "http://server:8080",
            timeout=15,
        )
        checks["denied_ingress_is_blocked"] = not denied_ok
        return checks
    finally:
        if created:
            kubectl(
                "delete",
                "namespace",
                namespace,
                "--wait=true",
                "--timeout=120s",
                timeout=150,
            )


def certify() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, reason: str) -> None:
        checks[name] = passed
        if not passed:
            failures.append(reason)

    resources: list[dict[str, Any]] = []
    errors: list[str] = []
    for kind in ("pods", "daemonsets"):
        ok, payload, detail = _kubectl_json("get", kind, "--all-namespaces", "-o", "json")
        if ok and payload is not None:
            resources.append(payload)
        else:
            errors.append(f"{kind}: {detail}")
    cni = detect_cni(resources)
    check(
        "cni_inventory_observed",
        bool(resources),
        "Kubernetes CNI inventory could not be observed",
    )
    check(
        "cni_known_to_enforce_networkpolicy",
        bool(cni["enforcement_expected"]),
        str(cni.get("reason") or "CNI is not known to enforce NetworkPolicy"),
    )
    mutation_performed = False
    if cni["enforcement_expected"]:
        namespace = f"gda-agentops-netpol-cert-{uuid.uuid4().hex[:8]}"
        try:
            mutation_performed = True
            probe_checks = _run_disposable_probe(kubectl=_kubectl, namespace=namespace)
            for name, passed in probe_checks.items():
                check(name, passed, f"NetworkPolicy probe check failed: {name}")
        except NetworkPolicyCertificationError as exc:
            check("disposable_policy_probe_completed", False, str(exc))
    report: dict[str, Any] = {
        "schema": "gda.agentops_networkpolicy_enforcement_certification.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "disposable_kubernetes_networkpolicy_probe",
        "cni": cni,
        "kubectl_inventory_errors": errors,
        "mutation_performed": mutation_performed,
        "checks": checks,
        "passed": bool(checks) and not failures,
        "failure_reasons": failures,
        "production_readiness_claimed": False,
    }
    report["report_sha256"] = canonical_json_fingerprint(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = certify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
