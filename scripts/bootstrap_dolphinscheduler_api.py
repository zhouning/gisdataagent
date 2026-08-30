#!/usr/bin/env python3
"""Idempotently bootstrap least-privilege objects in the DS sandbox."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


class BootstrapError(RuntimeError):
    pass


def _write_secret(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    rendered = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    _write_secret(path, rendered)


class DolphinSchedulerBootstrapClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _opener(self) -> urllib.request.OpenerDirector:
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def request(
        self,
        opener: urllib.request.OpenerDirector,
        method: str,
        path: str,
        *,
        form: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        body = urllib.parse.urlencode(form).encode("utf-8") if form else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if token:
            headers["token"] = token
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with opener.open(request, timeout=15) as response:
                payload = json.load(response)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise BootstrapError(f"DolphinScheduler request failed: {method} {path}") from exc
        if not isinstance(payload, dict) or payload.get("code") != 0:
            code = payload.get("code") if isinstance(payload, dict) else "invalid"
            raise BootstrapError(
                f"DolphinScheduler rejected {method} {path} with code {code}"
            )
        return payload.get("data")

    def login(self, username: str, password: str) -> urllib.request.OpenerDirector:
        opener = self._opener()
        self.request(
            opener,
            "POST",
            "/login",
            form={"userName": username, "userPassword": password},
        )
        return opener


def _page_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("totalList"), list):
        raise BootstrapError("DolphinScheduler paging response is invalid")
    items = value["totalList"]
    if not all(isinstance(item, dict) for item in items):
        raise BootstrapError("DolphinScheduler paging response contains invalid items")
    return items


def _one_by(items: list[dict[str, Any]], key: str, value: Any) -> dict[str, Any] | None:
    matches = [item for item in items if item.get(key) == value]
    if len(matches) > 1:
        raise BootstrapError(f"multiple DolphinScheduler objects share {key}={value}")
    return matches[0] if matches else None


def _read_secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise BootstrapError(f"secret file is empty: {path}")
    return value


def bootstrap(*, base_url: str, runtime_dir: Path) -> dict[str, Any]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.chmod(0o700)
    client = DolphinSchedulerBootstrapClient(base_url)
    admin_password = os.getenv(
        "DOLPHINSCHEDULER_BOOTSTRAP_ADMIN_PASSWORD", "dolphinscheduler123"
    )
    admin = client.login("admin", admin_password)

    tenants = _page_items(
        client.request(
            admin,
            "GET",
            "/tenants",
            query={"pageNo": 1, "pageSize": 100},
        )
    )
    tenant = _one_by(tenants, "tenantCode", "gda_sandbox")
    tenant_created = tenant is None
    if tenant is None:
        tenant = client.request(
            admin,
            "POST",
            "/tenants",
            form={
                "tenantCode": "gda_sandbox",
                "queueId": 1,
                "description": "GDA DataOps sandbox",
            },
        )
    if not isinstance(tenant, dict) or not isinstance(tenant.get("id"), int):
        raise BootstrapError("GDA DolphinScheduler tenant is invalid")

    addresses = client.request(admin, "GET", "/worker-groups/worker-address-list")
    if not isinstance(addresses, list) or not addresses:
        raise BootstrapError("no live DolphinScheduler worker address is available")
    groups = _page_items(
        client.request(
            admin,
            "GET",
            "/worker-groups",
            query={"pageNo": 1, "pageSize": 100},
        )
    )
    group = _one_by(groups, "name", "gda_dataops_sandbox")
    group_created = group is None
    group_form: dict[str, Any] = {
        "name": "gda_dataops_sandbox",
        "addrList": ",".join(sorted(str(value) for value in addresses)),
        "description": "GDA DataOps sandbox worker group",
    }
    if group is not None:
        group_form["id"] = group["id"]
    group = client.request(admin, "POST", "/worker-groups", form=group_form)

    password_path = runtime_dir / "service-password"
    if not password_path.exists():
        _write_secret(password_path, secrets.token_hex(8))
    service_password = _read_secret(password_path)
    users = client.request(admin, "GET", "/users/list")
    if not isinstance(users, list):
        raise BootstrapError("DolphinScheduler user list is invalid")
    user = _one_by(users, "userName", "gda_dataops")
    user_created = user is None
    if user is None:
        user = client.request(
            admin,
            "POST",
            "/users/create",
            form={
                "userName": "gda_dataops",
                "userPassword": service_password,
                "tenantId": tenant["id"],
                "queue": "default",
                "email": "gda-dataops@example.com",
                "state": 1,
            },
        )
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise BootstrapError("GDA DolphinScheduler service user is invalid")

    user_password_reconciled = False
    try:
        service = client.login("gda_dataops", service_password)
    except BootstrapError:
        client.request(
            admin,
            "POST",
            "/users/update",
            form={
                "id": user["id"],
                "userName": "gda_dataops",
                "userPassword": service_password,
                "tenantId": tenant["id"],
                "queue": user.get("queue") or "default",
                "email": user.get("email") or "gda-dataops@example.com",
                "phone": user.get("phone") or "",
                "state": 1,
                "timeZone": user.get("timeZone") or "Asia/Tokyo",
            },
        )
        service = client.login("gda_dataops", service_password)
        user_password_reconciled = True
    projects = _page_items(
        client.request(
            service,
            "GET",
            "/projects",
            query={"pageNo": 1, "pageSize": 100},
        )
    )
    project = _one_by(projects, "name", "gda_chongqing_dataops")
    project_created = project is None
    if project is None:
        project = client.request(
            service,
            "POST",
            "/projects",
            form={
                "projectName": "gda_chongqing_dataops",
                "description": "GDA Chongqing real-data DataOps sandbox",
            },
        )
    if not isinstance(project, dict) or not isinstance(project.get("code"), int):
        raise BootstrapError("GDA DolphinScheduler project is invalid")

    token_path = runtime_dir / "access-token"
    token_created = False
    token = _read_secret(token_path) if token_path.exists() else None
    if token:
        try:
            client.request(
                client._opener(),
                "GET",
                "/projects",
                query={"pageNo": 1, "pageSize": 1},
                token=token,
            )
        except BootstrapError:
            token = None
    if token is None:
        expires_at = datetime.now().replace(microsecond=0) + timedelta(days=365)
        token_record = client.request(
            service,
            "POST",
            "/access-tokens",
            form={
                "userId": user["id"],
                "expireTime": expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        if not isinstance(token_record, dict) or not token_record.get("token"):
            raise BootstrapError("DolphinScheduler token creation returned no token")
        token = str(token_record["token"])
        _write_secret(token_path, token)
        token_created = True

    profile = {
        "schema": "gda.dolphinscheduler_sandbox_profile.v1",
        "api_profile": "3.4",
        "server_version": "3.4.2",
        "base_url": base_url.rstrip("/"),
        "project_code": project["code"],
        "project_name": project["name"],
        "tenant_code": tenant["tenantCode"],
        "worker_group": group["name"],
        "token_file": token_path.resolve().as_posix(),
        "workload_subject": "workload:dolphinscheduler-gda-dataops",
        "policy_evaluator_subject": "workload:gda-policy-evaluator",
    }
    _write_json(runtime_dir / "profile.json", profile)
    return {
        "schema": "gda.dolphinscheduler_sandbox_bootstrap.v1",
        "status": "ready",
        "server_version": "3.4.2",
        "project_code": project["code"],
        "tenant_created": tenant_created,
        "worker_group_created": group_created,
        "user_created": user_created,
        "user_password_reconciled": user_password_reconciled,
        "project_created": project_created,
        "token_created": token_created,
        "profile_path": (runtime_dir / "profile.json").resolve().as_posix(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            bootstrap(base_url=args.base_url, runtime_dir=args.runtime_dir),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
