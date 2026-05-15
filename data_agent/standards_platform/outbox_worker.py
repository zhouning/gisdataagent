"""Independent outbox worker process.

Entrypoint:
    python -m data_agent.standards_platform.outbox_worker
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env before any module reads os.environ for DB credentials.
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

from . import outbox
from .config import StandardsConfig
from .handlers import dispatch
from ..observability import get_logger, setup_logging

setup_logging()
logger = get_logger("standards_platform.outbox_worker")

_shutdown = False


def _handle_signal(sig, frame):
    global _shutdown
    _shutdown = True
    logger.info("received signal %s — draining and shutting down", sig)


def run_once(*, batch_size: int, max_attempts: int) -> int:
    events = outbox.claim_batch(limit=batch_size)
    for evt in events:
        try:
            dispatch(evt)
            outbox.complete(evt["id"])
        except Exception as e:  # keep worker up on handler errors
            logger.exception("handler failed for event %s: %s", evt.get("id"), e)
            outbox.fail(evt["id"], str(e), max_attempts=max_attempts)
    return len(events)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Standards Platform outbox worker (independent process).")
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--once", action="store_true",
                    help="process a single batch and exit (for CI).")
    args = ap.parse_args(argv)

    cfg = StandardsConfig.from_env()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    logger.info("outbox_worker starting (interval=%ss, max_attempts=%d)",
                cfg.outbox_worker_interval_sec, cfg.outbox_max_attempts)

    if args.once:
        run_once(batch_size=args.batch_size, max_attempts=cfg.outbox_max_attempts)
        return 0

    while not _shutdown:
        run_once(batch_size=args.batch_size, max_attempts=cfg.outbox_max_attempts)
        for _ in range(cfg.outbox_worker_interval_sec):
            if _shutdown: break
            time.sleep(1)
    logger.info("outbox_worker exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
