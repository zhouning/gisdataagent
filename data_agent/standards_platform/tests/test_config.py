import os
from data_agent.standards_platform.config import StandardsConfig


def test_defaults_when_env_missing(monkeypatch):
    for k in ("STANDARDS_WEB_DOMAINS_ALLOWLIST",
              "STANDARDS_OUTBOX_WORKER_INTERVAL_SEC",
              "STANDARDS_OUTBOX_MAX_ATTEMPTS"):
        monkeypatch.delenv(k, raising=False)
    cfg = StandardsConfig.from_env()
    assert cfg.outbox_worker_interval_sec == 5
    assert cfg.outbox_max_attempts == 5
    assert "std.samr.gov.cn" in cfg.web_domains_allowlist
    assert "openstd.samr.gov.cn" in cfg.web_domains_allowlist
    assert "ogc.org" in cfg.web_domains_allowlist
    assert "iso.org" in cfg.web_domains_allowlist
    assert "arxiv.org" in cfg.web_domains_allowlist
    assert "scholar.google.com" in cfg.web_domains_allowlist
    assert "cnki.net" in cfg.web_domains_allowlist


def test_overrides_from_env(monkeypatch):
    monkeypatch.setenv("STANDARDS_WEB_DOMAINS_ALLOWLIST", "example.com,foo.org")
    monkeypatch.setenv("STANDARDS_OUTBOX_WORKER_INTERVAL_SEC", "12")
    monkeypatch.setenv("STANDARDS_OUTBOX_MAX_ATTEMPTS", "9")
    cfg = StandardsConfig.from_env()
    assert cfg.web_domains_allowlist == {"example.com", "foo.org"}
    assert cfg.outbox_worker_interval_sec == 12
    assert cfg.outbox_max_attempts == 9
