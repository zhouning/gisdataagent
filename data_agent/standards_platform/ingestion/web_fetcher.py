"""HTTP fetcher with allowlist, SSRF guard, robots.txt, size cap, manual paste."""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.robotparser
import uuid
from pathlib import Path

import requests
from sqlalchemy import text

from ...db_engine import get_engine
from ...observability import get_logger
from ...user_context import get_user_upload_dir
from .. import config as cfg_mod

logger = get_logger("standards_platform.ingestion.web_fetcher")


class NotAllowed(Exception):
    """Raised when a URL is rejected by allowlist, SSRF guard, or robots."""


_PRIVATE_NETS = [ipaddress.ip_network(n) for n in
    ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
     "127.0.0.0/8", "169.254.0.0/16", "::1/128", "fc00::/7")]


def _is_private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if any(addr in net for net in _PRIVATE_NETS):
            return True
    return False


def _check_allowed(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    cfg = cfg_mod.StandardsConfig.from_env()
    if host not in cfg.web_domains_allowlist:
        raise NotAllowed(f"host not in allowlist: {host}")
    if _is_private(host):
        raise NotAllowed(f"refusing private/loopback target: {host}")
    return host


def fetch(url: str, *, user_agent: str = "GIS-Data-Agent-Standards/0.1",
          max_bytes: int = 10 * 1024 * 1024, timeout: int = 30) -> dict:
    host = _check_allowed(url)
    robots_url = f"https://{host}/robots.txt"
    try:
        rb = requests.get(robots_url, headers={"User-Agent": user_agent}, timeout=10)
        rp = urllib.robotparser.RobotFileParser(); rp.parse(rb.text.splitlines())
        if not rp.can_fetch(user_agent, url):
            raise NotAllowed(f"blocked by robots.txt: {url}")
    except requests.RequestException:
        logger.warning("robots.txt unreachable for %s — proceeding", host)

    rsp = requests.get(url, headers={"User-Agent": user_agent},
                       timeout=timeout, stream=True)
    chunks, size, truncated = [], 0, False
    for chunk in rsp.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        if size + len(chunk) > max_bytes:
            chunks.append(chunk[: max_bytes - size]); truncated = True; break
        chunks.append(chunk); size += len(chunk)
    body = b"".join(chunks)
    return {
        "url": url, "status": rsp.status_code,
        "headers": dict(rsp.headers), "body": body, "truncated": truncated,
    }


def save_manual(url: str, *, pasted_text: str, user_id: str) -> str:
    """Manual-paste fallback when the source rejects automated fetch."""
    sandbox = Path(get_user_upload_dir()) / "standards" / "snapshots"
    sandbox.mkdir(parents=True, exist_ok=True)
    snap_id = str(uuid.uuid4())
    txt_path = sandbox / f"{snap_id}.txt"
    txt_path.write_text(pasted_text, encoding="utf-8")
    eng = get_engine()
    with eng.connect() as conn:
        conn.execute(text("""
            INSERT INTO std_web_snapshot (id, url, http_status, html_path, extracted_text)
            VALUES (:i, :u, 0, :p, :t)
        """), {"i": snap_id, "u": url, "p": str(txt_path), "t": pasted_text[:200000]})
        conn.commit()
    return snap_id
