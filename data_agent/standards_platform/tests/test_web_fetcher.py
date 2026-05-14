import pytest
from unittest.mock import patch, MagicMock

from data_agent.standards_platform.ingestion import web_fetcher as wf


def test_rejects_url_outside_allowlist():
    with pytest.raises(wf.NotAllowed):
        wf.fetch("https://evil.example.com/spec.pdf")


@pytest.mark.parametrize("ip_url", [
    "http://10.0.0.1/x", "http://192.168.1.1/x",
    "http://172.16.5.5/x", "http://127.0.0.1/x", "http://169.254.1.1/x",
])
def test_rejects_ssrf_targets(ip_url):
    with pytest.raises(wf.NotAllowed):
        wf.fetch(ip_url)


def test_respects_robots_disallow():
    fake_resp = MagicMock(status_code=200, text="User-agent: *\nDisallow: /\n",
                          headers={"content-type": "text/plain"})
    with patch("data_agent.standards_platform.ingestion.web_fetcher.requests.get",
               return_value=fake_resp):
        with pytest.raises(wf.NotAllowed, match="robots"):
            wf.fetch("https://arxiv.org/abs/2401.00001")


def test_truncates_when_over_max_bytes():
    big = b"a" * (20 * 1024 * 1024)
    robots = MagicMock(status_code=200, text="User-agent: *\nAllow: /\n",
                       headers={"content-type":"text/plain"})
    page = MagicMock(status_code=200, content=big,
                     headers={"content-type": "text/html"})
    page.iter_content = lambda chunk_size: [big[:chunk_size]]
    with patch("data_agent.standards_platform.ingestion.web_fetcher.requests.get",
               side_effect=[robots, page]):
        out = wf.fetch("https://arxiv.org/abs/2401.00002", max_bytes=1024)
    assert len(out["body"]) <= 1024
    assert out["truncated"] is True


def test_manual_paste_persists_snapshot():
    from data_agent.user_context import current_user_id
    current_user_id.set("alice")
    snap_id = wf.save_manual("https://std.samr.gov.cn/abc",
                              pasted_text="完整正文……", user_id="alice")
    assert isinstance(snap_id, str) and len(snap_id) > 0
