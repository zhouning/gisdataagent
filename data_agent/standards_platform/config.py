"""Env-driven configuration for the standards_platform subsystem."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_ALLOWLIST = (
    "std.samr.gov.cn",
    "openstd.samr.gov.cn",
    "ogc.org",
    "iso.org",
    "arxiv.org",
    "scholar.google.com",
    "cnki.net",
)


@dataclass(frozen=True)
class StandardsConfig:
    web_domains_allowlist: frozenset[str] = field(default_factory=lambda: frozenset(DEFAULT_ALLOWLIST))
    outbox_worker_interval_sec: int = 5
    outbox_max_attempts: int = 5
    web_max_bytes: int = 10 * 1024 * 1024  # 10 MB
    rate_limit_per_minute: int = 20

    @classmethod
    def from_env(cls) -> "StandardsConfig":
        raw = os.getenv("STANDARDS_WEB_DOMAINS_ALLOWLIST", "")
        if raw.strip():
            allow = frozenset(d.strip() for d in raw.split(",") if d.strip())
        else:
            allow = frozenset(DEFAULT_ALLOWLIST)
        return cls(
            web_domains_allowlist=allow,
            outbox_worker_interval_sec=int(os.getenv("STANDARDS_OUTBOX_WORKER_INTERVAL_SEC", "5")),
            outbox_max_attempts=int(os.getenv("STANDARDS_OUTBOX_MAX_ATTEMPTS", "5")),
        )
