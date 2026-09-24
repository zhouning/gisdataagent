"""Small dependency-free Kubernetes API client for in-cluster Job control."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class KubernetesApiError(RuntimeError):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"kubernetes_api_{status}:{detail}")


class InClusterKubernetesClient:
    def __init__(
        self,
        namespace: str | None = None,
        *,
        api_base: str | None = None,
        token: str | None = None,
        ca_path: str | None = None,
    ):
        self.namespace = namespace or os.environ.get("HYDRO_K8S_NAMESPACE", "gis-agent-hydro-dev")
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "")
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        self.api_base = (api_base or (f"https://{host}:{port}" if host else "")).rstrip("/")
        self.token = token or self._read_optional(
            "/var/run/secrets/kubernetes.io/serviceaccount/token"
        )
        self.ca_path = ca_path or "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        self._ssl = (
            ssl.create_default_context(cafile=self.ca_path)
            if Path(self.ca_path).exists()
            else ssl._create_unverified_context()
        )

    @staticmethod
    def _read_optional(path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.api_base:
            raise KubernetesApiError(503, "kubernetes_api_not_configured")
        url = f"{self.api_base}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, context=self._ssl, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:2_000]
            raise KubernetesApiError(error.code, detail) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise KubernetesApiError(503, str(error)) from error

    def _request_text(self, method: str, path: str) -> str:
        if not self.api_base:
            raise KubernetesApiError(503, "kubernetes_api_not_configured")
        request = urllib.request.Request(
            f"{self.api_base}{path}",
            method=method,
            headers={"Accept": "application/json"},
        )
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, context=self._ssl, timeout=20) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:2_000]
            raise KubernetesApiError(error.code, detail) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise KubernetesApiError(503, str(error)) from error

    def create_job(self, job: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", f"/apis/batch/v1/namespaces/{urllib.parse.quote(self.namespace)}/jobs", job
        )

    def get_job(self, name: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/apis/batch/v1/namespaces/{urllib.parse.quote(self.namespace)}/jobs/{urllib.parse.quote(name)}",
        )

    def delete_job(self, name: str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/apis/batch/v1/namespaces/{urllib.parse.quote(self.namespace)}/jobs/{urllib.parse.quote(name)}",
        )

    def list_pods_for_job(self, name: str) -> dict[str, Any]:
        selector = urllib.parse.quote(f"job-name={name}", safe="")
        return self._request(
            "GET",
            f"/api/v1/namespaces/{urllib.parse.quote(self.namespace)}/pods?labelSelector={selector}",
        )

    def get_pod_logs(self, name: str, *, tail_lines: int = 200) -> str:
        query = urllib.parse.urlencode({"tailLines": max(1, min(int(tail_lines), 2_000))})
        return self._request_text(
            "GET",
            f"/api/v1/namespaces/{urllib.parse.quote(self.namespace)}/pods/"
            f"{urllib.parse.quote(name)}/log?{query}",
        )


def job_manifest(
    manifest: dict[str, Any],
    *,
    image: str,
    namespace: str,
    pvc_name: str,
    run_root: str = "/data/runs",
) -> dict[str, Any]:
    run_id = str(manifest["run_id"])
    profile = manifest["request"]["resource_profile"]
    resources: dict[str, Any] = {
        "cpu_small": {
            "requests": {"cpu": "250m", "memory": "512Mi"},
            "limits": {"cpu": "2", "memory": "4Gi"},
        },
        "cpu_large": {
            "requests": {"cpu": "1", "memory": "2Gi"},
            "limits": {"cpu": "8", "memory": "16Gi"},
        },
        "gpu": {
            "requests": {"cpu": "2", "memory": "8Gi", "nvidia.com/gpu": "1"},
            "limits": {"cpu": "8", "memory": "32Gi", "nvidia.com/gpu": "1"},
        },
    }[profile]
    container: dict[str, Any] = {
        "name": "hydro-worker",
        "image": image,
        "imagePullPolicy": "IfNotPresent",
        "command": ["python", "-m", "data_agent.hydro_workbench.worker", "--run-id", run_id],
        "env": [
            {"name": "HYDRO_RUN_ROOT", "value": run_root},
            {"name": "ABU_DHABI_HYDRO_RUN_ROOT", "value": run_root},
        ],
        "volumeMounts": [
            {"name": "hydro-runs", "mountPath": run_root},
            {"name": "tmp", "mountPath": "/tmp"},
        ],
        "resources": resources,
        "securityContext": {
            "seccompProfile": {"type": "RuntimeDefault"},
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
        },
    }
    pod_spec: dict[str, Any] = {
        "restartPolicy": "Never",
        "serviceAccountName": "hydro-worker",
        # The GIS API runs as UID 999 while the dedicated solver image runs as
        # UID 10001.  A shared supplemental group lets both sides exchange
        # manifests/status/results on the PVC without making artifacts public.
        "securityContext": {
            "runAsUser": 10001,
            "runAsGroup": 999,
            "fsGroup": 999,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "containers": [container],
        "volumes": [
            {"name": "hydro-runs", "persistentVolumeClaim": {"claimName": pvc_name}},
            {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}},
        ],
    }
    if profile == "gpu":
        pod_spec["nodeSelector"] = {"hydro.gisdataagent.io/gpu": "true"}
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": manifest["runtime"]["job_name"],
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": "hydro-run",
                "hydro.gisdataagent.io/run-id": run_id,
                "hydro.gisdataagent.io/model-type": str(manifest["request"]["model_type"]),
                "hydro.gisdataagent.io/input-mode": str(manifest["request"]["input_mode"]),
                "hydro.gisdataagent.io/resource-profile": str(profile),
            },
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": int(
                manifest.get("runtime", {}).get("active_deadline_seconds", 7_200)
            ),
            "ttlSecondsAfterFinished": 3_600,
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/name": "hydro-run",
                        "job-name": manifest["runtime"]["job_name"],
                        "hydro.gisdataagent.io/run-id": run_id,
                    }
                },
                "spec": pod_spec,
            },
        },
    }
