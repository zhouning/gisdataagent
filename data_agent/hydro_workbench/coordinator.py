"""Run coordinator: freeze manifest, submit Job, expose durable status."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .contracts import ManifestValidationError, build_run_manifest, seal_manifest
from .k8s_api import InClusterKubernetesClient, KubernetesApiError, job_manifest
from .storage import read_json, read_manifest, read_status, run_dir, update_status, write_manifest

try:
    from ..user_context import current_tenant_id, current_user_id, current_user_role
except ImportError:  # pragma: no cover - standalone package fallback
    current_user_id = current_tenant_id = current_user_role = None


class HydroRunAccessError(PermissionError):
    """The authenticated principal is not allowed to access a run."""


class HydroRunStateError(RuntimeError):
    """A requested lifecycle transition is no longer valid."""


class HydroRunCoordinator:
    def __init__(self, *, root: Path | None = None, k8s_client: Any | None = None):
        self.root = root or Path(os.environ.get("HYDRO_RUN_ROOT", "/data/runs"))
        self.namespace = os.environ.get("HYDRO_K8S_NAMESPACE", "gis-agent-hydro-dev")
        self.pvc_name = os.environ.get("HYDRO_RUNS_PVC", "hydro-runs")
        self.worker_image = os.environ.get(
            "HYDRO_WORKER_IMAGE", "abu-dhabi-hydrodynamics:workbench-dev"
        )
        self.allow_development_fixtures = (
            os.environ.get("HYDRO_ALLOW_DEVELOPMENT_FIXTURES", "false").lower() == "true"
        )
        self.client = k8s_client or InClusterKubernetesClient(self.namespace)

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        manifest = build_run_manifest(payload)
        owner_id = current_user_id.get() if current_user_id is not None else "anonymous"
        tenant_id = current_tenant_id.get() if current_tenant_id is not None else ""
        owner_id = str(owner_id or "anonymous")[:256]
        tenant_id = str(tenant_id or "")[:256]
        manifest["security"] = {
            "owner_id": owner_id,
            "tenant_id": tenant_id,
        }
        # The security envelope is server-owned and must be covered by the
        # digest written to the immutable manifest.
        seal_manifest(manifest)
        if (
            manifest["request"]["input_mode"] == "development_fixture"
            and not self.allow_development_fixtures
        ):
            raise ManifestValidationError(
                [
                    {
                        "field": "input_mode",
                        "message": "development fixtures are disabled in this environment",
                    }
                ]
            )
        if manifest["request"]["input_mode"] == "customer_mount":
            raise ManifestValidationError(
                [
                    {
                        "field": "input_mode",
                        "message": (
                            "customer data execution is fail-closed until the GDB/DTM ETL "
                            "adapter produces model-ready SWMM INP and ANUGA grid inputs"
                        ),
                    }
                ]
            )
        if (
            manifest["request"]["resource_profile"] == "gpu"
            and os.environ.get("HYDRO_GPU_ENABLED", "false").lower() != "true"
        ):
            raise ManifestValidationError(
                [
                    {
                        "field": "resource_profile",
                        "message": "GPU profile is disabled in this environment",
                    }
                ]
            )
        write_manifest(manifest, self.root)
        job = job_manifest(
            manifest,
            image=self.worker_image,
            namespace=self.namespace,
            pvc_name=self.pvc_name,
            run_root=str(self.root),
        )
        try:
            created = self.client.create_job(job)
        except Exception as error:
            update_status(
                manifest["run_id"],
                "submit_failed",
                progress=0,
                root=self.root,
                error=str(error),
                job_name=manifest["runtime"]["job_name"],
            )
            raise
        update_status(
            manifest["run_id"],
            "queued",
            progress=5,
            root=self.root,
            job_name=manifest["runtime"]["job_name"],
            kubernetes_uid=created.get("metadata", {}).get("uid"),
        )
        return {
            "run_id": manifest["run_id"],
            "status": "queued",
            "manifest": manifest,
            "job": {"name": manifest["runtime"]["job_name"], "namespace": self.namespace},
        }

    def status(self, run_id: str) -> dict[str, Any]:
        manifest = read_manifest(run_id, self.root)
        self.assert_access(manifest)
        self._assert_manifest_integrity(manifest)
        status = read_status(run_id, self.root)
        job_name = str(manifest["runtime"]["job_name"])
        job_status: dict[str, Any] = {}
        result_ready = self._result_ready(run_id)
        if result_ready and status.get("status") not in {"completed", "failed", "cancelled"}:
            update_status(run_id, "completed", progress=100, root=self.root, job_name=job_name)
            status = read_status(run_id, self.root)
        if status.get("status") == "completed" and not result_ready:
            update_status(
                run_id,
                "failed",
                progress=100,
                root=self.root,
                job_name=job_name,
                error="result_missing_after_completion",
            )
            status = read_status(run_id, self.root)
        try:
            job = self.client.get_job(job_name)
            job_status = job.get("status") or {}
            if job_status.get("succeeded"):
                if result_ready and status.get("status") not in {"completed", "failed"}:
                    update_status(
                        run_id, "completed", progress=100, root=self.root, job_name=job_name
                    )
                    status = read_status(run_id, self.root)
                elif not result_ready and status.get("status") not in {"failed", "cancelled"}:
                    update_status(
                        run_id,
                        "failed",
                        progress=100,
                        root=self.root,
                        job_name=job_name,
                        error="result_missing_after_job_success",
                    )
                    status = read_status(run_id, self.root)
            elif job_status.get("failed") and status.get("status") not in {"completed", "failed"}:
                update_status(
                    run_id,
                    "failed",
                    progress=100,
                    root=self.root,
                    job_name=job_name,
                    error="kubernetes_job_failed",
                )
                status = read_status(run_id, self.root)
        except KubernetesApiError as error:
            job_status = {"error": error.detail, "status_code": error.status}
        return {
            "run_id": run_id,
            "manifest": manifest,
            "status": status,
            "result_available": result_ready,
            "kubernetes": {"job_name": job_name, "job_status": job_status},
        }

    def logs(self, run_id: str) -> dict[str, Any]:
        manifest = read_manifest(run_id, self.root)
        self.assert_access(manifest)
        self._assert_manifest_integrity(manifest)
        job_name = str(manifest["runtime"]["job_name"])
        pods = self.client.list_pods_for_job(job_name).get("items") or []
        if not pods:
            return {"run_id": run_id, "job_name": job_name, "logs": "", "status": "pending"}
        pod_name = str(pods[0].get("metadata", {}).get("name") or "")
        return {
            "run_id": run_id,
            "job_name": job_name,
            "pod_name": pod_name,
            "logs": self.client.get_pod_logs(pod_name),
            "status": "available",
        }

    def cancel(self, run_id: str) -> dict[str, Any]:
        manifest = read_manifest(run_id, self.root)
        self.assert_access(manifest)
        self._assert_manifest_integrity(manifest)
        current_status = read_status(run_id, self.root)
        if current_status.get("status") not in {"queued", "running"}:
            raise HydroRunStateError(f"run_not_cancellable:{current_status.get('status', 'unknown')}")
        job_name = str(manifest["runtime"]["job_name"])
        deleted = self.client.delete_job(job_name)
        update_status(run_id, "cancelled", progress=100, root=self.root, job_name=job_name)
        return {"run_id": run_id, "status": "cancelled", "job": deleted}

    def assert_access(self, manifest_or_run_id: dict[str, Any] | str) -> None:
        manifest = (
            read_manifest(manifest_or_run_id, self.root)
            if isinstance(manifest_or_run_id, str)
            else manifest_or_run_id
        )
        security = manifest.get("security") or {}
        owner_id = str(security.get("owner_id") or "anonymous")
        tenant_id = str(security.get("tenant_id") or "")
        current_id = str(current_user_id.get() if current_user_id is not None else "anonymous")
        current_tenant = str(current_tenant_id.get() if current_tenant_id is not None else "")
        role = str(current_user_role.get() if current_user_role is not None else "anonymous")
        if role == "admin":
            return
        if owner_id != current_id or (tenant_id and tenant_id != current_tenant):
            raise HydroRunAccessError("hydro_run_access_denied")

    def assert_integrity(self, run_id: str) -> None:
        self._assert_manifest_integrity(read_manifest(run_id, self.root))

    def _result_ready(self, run_id: str) -> bool:
        path = run_dir(run_id, self.root) / "results" / "result.json"
        try:
            payload = read_json(path)
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("schema") == "gwm.abu_dhabi_flood.hydro_run_result.v1"
            and payload.get("run_id") == run_id
        )

    @staticmethod
    def _assert_manifest_integrity(manifest: dict[str, Any]) -> None:
        from .contracts import manifest_sha256

        expected = str((manifest.get("immutability") or {}).get("sha256") or "")
        if not expected or expected != manifest_sha256(manifest):
            raise HydroRunStateError("manifest_integrity_check_failed")
