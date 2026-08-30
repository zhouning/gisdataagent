#!/usr/bin/env python3
"""Run the real automatic ApprovalCase expiry acceptance rehearsal."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from data_agent.agentops_temporal_approval_expiry_rehearsal import (
    run_rehearsal,
    write_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="gda-agentops-sandbox")
    parser.add_argument("--task-queue", default="agentops-step-hitl-expiry-rehearsal")
    parser.add_argument("--expiry-seconds", type=float, default=1.5)
    parser.add_argument(
        "--admin-database-url",
        default=os.environ.get("GDA_REHEARSAL_ADMIN_DATABASE_URL"),
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    args = parser.parse_args()
    if not args.admin_database_url:
        parser.error("--admin-database-url or GDA_REHEARSAL_ADMIN_DATABASE_URL is required")
    report, history_json = asyncio.run(
        run_rehearsal(
            frontend_target=args.frontend,
            namespace_ref=args.namespace,
            task_queue_ref=args.task_queue,
            admin_database_url=args.admin_database_url,
            expiry_seconds=args.expiry_seconds,
        )
    )
    write_report(report, args.report)
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.history.write_text(history_json + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
