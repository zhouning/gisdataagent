"""Real browser E2E for the longest-bridge 100m AMap POI map handoff."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("GIS_AGENT_E2E_URL", "http://127.0.0.1:8000")
USERNAME = os.environ.get("GIS_AGENT_E2E_USER", "admin")
PASSWORD = os.environ.get("GIS_AGENT_E2E_PASSWORD", "")
PROMPT = "@NL2SQL 统计距离道路网络中最长桥梁100米范围内的高德POI数量。"
ARTIFACT_DIR = Path("tests/e2e/artifacts/nl2sql_longest_bridge_map_2026_07_30")


def main() -> None:
    if not PASSWORD:
        raise RuntimeError("GIS_AGENT_E2E_PASSWORD is required for real browser E2E")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.locator("#username").fill(USERNAME)
        page.locator("#password").fill(PASSWORD)
        page.get_by_role("button", name="登录").click()
        page.locator(".app-header").wait_for(state="visible", timeout=30_000)
        page.wait_for_timeout(12_000)

        box = page.get_by_placeholder("输入消息... (Enter 发送)")
        box.fill(PROMPT)
        box.press("Enter")

        response = page.locator(
            ".chat-message.assistant",
            has_text="POI数量：35",
        ).last
        response.wait_for(timeout=120_000)
        response_text = response.inner_text()
        assert "已默认加载地图：高德 POI 35 个" in response_text
        assert "同一 PostGIS 查询快照" in response_text

        map_update = page.wait_for_function(
            """() => {
                const update = window.__lastMapUpdate;
                return update?.summary?.query_type === 'longest_bridge_poi_100m'
                    ? update
                    : null;
            }""",
            timeout=30_000,
        ).json_value()
        assert map_update["summary"]["scalar_poi_count"] == 35
        assert map_update["summary"]["poi_feature_count"] == 35
        assert map_update["summary"]["bridge_feature_count"] == 1
        assert map_update["summary"]["buffer_feature_count"] == 1
        assert map_update["summary"]["geometry_snapshot"] == "single_postgis_statement"
        assert [layer["type"] for layer in map_update["layers"]] == [
            "polygon",
            "line",
            "point",
        ]

        feature_counts = page.evaluate(
            """async (update) => {
                const counts = {};
                for (const layer of update.layers) {
                    const response = await fetch(`/api/user/files/${layer.geojson}`, {
                        credentials: 'include',
                    });
                    if (!response.ok) throw new Error(`${layer.name}: ${response.status}`);
                    const geojson = await response.json();
                    counts[layer.type] = geojson.features.length;
                }
                return counts;
            }""",
            map_update,
        )
        assert feature_counts == {"polygon": 1, "line": 1, "point": 35}

        page.wait_for_function(
            """() => Array.from(
                document.querySelectorAll('.leaflet-overlay-pane path.leaflet-interactive')
            ).filter(path => path.getAttribute('fill') === '#2563eb').length === 35""",
            timeout=30_000,
        )
        page.locator(".layer-control-toggle").click()
        for layer in map_update["layers"]:
            page.get_by_text(layer["name"], exact=True).wait_for(timeout=10_000)

        (ARTIFACT_DIR / "map_update.json").write_text(
            json.dumps(map_update, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (ARTIFACT_DIR / "verification.json").write_text(
            json.dumps(
                {
                    "prompt": PROMPT,
                    "response_contains_count_35": True,
                    "feature_counts": feature_counts,
                    "rendered_poi_paths": 35,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        page.screenshot(path=str(ARTIFACT_DIR / "result.png"), full_page=True)
        browser.close()

    print(json.dumps({
        "status": "passed",
        "prompt": PROMPT,
        "feature_counts": feature_counts,
        "bridge_osm_id": map_update["summary"]["bridge_osm_id"],
        "artifacts": str(ARTIFACT_DIR),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
