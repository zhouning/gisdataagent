#!/usr/bin/env python3
"""Small polling collector for a Windows shared folder or removable disk.

Run it as a Windows Task Scheduler job or wrap it with NSSM/WinSW.  It does
not require Docker, a message broker, or internet access.  The durable run
manifests make a restart after power loss idempotent at the asset hash level.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import time
from pathlib import Path

from data_agent.offline_ingest import OfflineIngestStore, sha256_tree


def _iter_candidates(inbox: Path):
    for item in sorted(inbox.iterdir()):
        if item.name.startswith(".") or item.name.endswith(".part"):
            continue
        if item.is_dir() and not item.name.lower().endswith(".gdb"):
            # A directory may contain several GDB/imagery/model assets; the
            # core scanner will discover its children in one run.
            yield item
        elif item.is_file() or item.name.lower().endswith(".gdb"):
            yield item


def _signature(path: Path) -> dict[str, int]:
    """Cheap pre-hash signature used to avoid ingesting a still-copying asset."""
    if path.is_file():
        stat = path.stat()
        return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "files": 1}
    total = 0
    latest = 0
    count = 0
    for child in path.rglob("*"):
        if child.is_file():
            stat = child.stat()
            total += stat.st_size
            latest = max(latest, stat.st_mtime_ns)
            count += 1
    return {"size": total, "mtime_ns": latest, "files": count}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _atomic_state_write(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def process_once(
    inbox: Path,
    store: OfflineIngestStore,
    state_path: Path,
    *,
    settle_seconds: int = 60,
) -> int:
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
    processed = 0
    for item in _iter_candidates(inbox):
        key = str(item.resolve())
        signature = _signature(item)
        previous = state.get(key) or {}
        if previous.get("signature") != signature:
            state[key] = {
                "signature": signature,
                "status": "waiting_for_stability",
                "observed_at": time.time(),
            }
            continue
        if time.time() - float(previous.get("observed_at", time.time())) < max(0, settle_seconds):
            continue
        digest = sha256_tree(item)
        contract_hash = None
        contract_path = os.environ.get("GDA_STANDARD_CONTRACTS", "").strip()
        if contract_path and Path(contract_path).expanduser().is_file():
            contract_hash = sha256_tree(Path(contract_path).expanduser())
        if (
            previous.get("sha256") == digest
            and previous.get("status") in {"succeeded", "review"}
            and previous.get("contract_sha256") == contract_hash
        ):
            continue
        try:
            result = store.scan_local_path(item, actor="windows-collector")
            state[key] = {
                "signature": signature,
                "sha256": digest,
                "contract_sha256": contract_hash,
                "run_id": result["run_id"],
                "status": result["status"],
                "processed_at": result.get("finished_at"),
            }
            processed += 1
        except Exception as exc:
            state[key] = {
                "signature": signature,
                "sha256": digest,
                "contract_sha256": contract_hash,
                "status": "error",
                "error": str(exc),
            }
            logging.getLogger("windows_ingest_worker").exception("ingest failed for %s", item)
    _atomic_state_write(state_path, state)
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description="GIS Data Agent Windows offline ingest worker")
    parser.add_argument("--inbox", required=True, help="shared folder or removable disk directory")
    parser.add_argument("--lake", default=os.environ.get("GDA_FILE_LAKE_ROOT", "./file_lake"))
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument(
        "--settle-seconds",
        type=int,
        default=_env_int("GDA_INGEST_SETTLE_SECONDS", 60),
        help="wait this long after a source signature stops changing",
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    inbox = Path(args.inbox).expanduser().resolve()
    if not inbox.is_dir():
        parser.error(f"inbox directory does not exist: {inbox}")
    os.environ["GDA_LOCAL_INGEST_DIRS"] = str(inbox)
    store = OfflineIngestStore(args.lake)
    state_path = store.root / "collector_state.json"
    log = logging.getLogger("windows_ingest_worker")
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    while True:
        count = process_once(inbox, store, state_path, settle_seconds=max(0, args.settle_seconds))
        log.info("collector cycle complete inbox=%s processed=%d", inbox, count)
        if args.once:
            return 0
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
