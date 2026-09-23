"""Run coordinator: freeze manifest, submit Job, expose durable status."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .contracts import ManifestValidationError, build_run_manifest
from .k8s_api import InClusterKubernetesClient, KubernetesApiError, job_manifest
from .storage import read_manifest, read_status, update_status, write_manifest


class HydroRunCoordinator:
    def __init__(self, *, root: Path | None = None, k8s_client: Any | None = None):
        self.root = root or Path(os.environ.get("HYDRO_RUN_ROOT", "/data/runs"))
        self.namespace = os.environ.get("HYDRO_K8S_NAMESPACE", "gis-agent-hydro-dev")
        self.pvc_name = os.environ.get("HYDRO_RUNS_PVC", "hydro-runs")
        self.worker_image = os.environ.get(
            "HYDRO_WORKER_IMAGE", "abu-dhabi-hydrodynamics:workbench-dev"
        )
        self.client = k8s_client or InClusterKubernetesClient(self.namespace)

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        manifest = build_run_manifest(payload)
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
        status = read_status(run_id, self.root)
        job_name = str(manifest["runtime"]["job_name"])
        job_status: dict[str, Any] = {}
        try:
            job = self.client.get_job(job_name)
            job_status = job.get("status") or {}
            if job_status.get("succeeded"):
                if status.get("status") not in {"completed", "failed"}:
                    update_status(
                        run_id, "completed", progress=100, root=self.root, job_name=job_name
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
            "kubernetes": {"job_name": job_name, "job_status": job_status},
        }

    def logs(self, run_id: str) -> dict[str, Any]:
        manifest = read_manifest(run_id, self.root)
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
        job_name = str(manifest["runtime"]["job_name"])
        deleted = self.client.delete_job(job_name)
        update_status(run_id, "cancelled", progress=100, root=self.root, job_name=job_name)
        return {"run_id": run_id, "status": "cancelled", "job": deleted}
