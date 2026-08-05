import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
QUERY = "运行和平村用地转换辅助预审，并在地图上展示结果。"
ARTIFACT_DIR = Path("tests/e2e/artifacts/ontology-heping-review")
EXPECTED_LAYERS = [
    "和平村 · 规划变化地块",
    "和平村 · 空间约束",
    "和平村 · 建设用地管制区",
]


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        token = os.getenv("GIS_AGENT_E2E_TOKEN", "").strip()
        if token:
            page.context.add_cookies(
                [
                    {
                        "name": "access_token",
                        "value": token,
                        "url": BASE_URL,
                        "httpOnly": True,
                        "sameSite": "Lax",
                    }
                ]
            )
        page.goto(BASE_URL, wait_until="domcontentloaded")
        if not token:
            page.locator("#username").fill(os.getenv("GIS_AGENT_E2E_USER", "admin"))
            page.locator("#password").fill(os.getenv("GIS_AGENT_E2E_PASSWORD", "admin123"))
            page.get_by_role("button", name="登录").click()
        page.locator(".app-header").wait_for(state="visible", timeout=30_000)

        chat_input = page.get_by_placeholder("输入消息... (Enter 发送)")
        chat_input.wait_for(state="visible", timeout=30_000)
        page.wait_for_timeout(3_000)
        chat_input.fill(QUERY)
        page.locator(".btn-send").click()
        page.locator(".chat-message.user", has_text=QUERY).wait_for(
            state="visible", timeout=10_000
        )

        answer = page.locator(
            ".chat-message.assistant .message-content",
            has_text="识别 445 个变化地块",
        )
        answer.wait_for(state="visible", timeout=120_000)
        answer_text = answer.inner_text()
        assert "25 个空间冲突" in answer_text
        assert "108 个审批证据缺口" in answer_text
        assert "辅助预审，不替代法定审批或行政决定" in answer_text
        assert "地图已加载 3 个结果图层" in answer_text
        assert "执行证明：OKF 0.2 计算契约验证通过" in answer_text
        assert "未识别到具体的质检模板" not in answer_text

        map_payload = page.wait_for_function(
            "() => window.__lastMapUpdate?.layers?.length === 3 "
            "? window.__lastMapUpdate : null",
            timeout=30_000,
        ).json_value()
        assert [layer["name"] for layer in map_payload["layers"]] == EXPECTED_LAYERS

        ontology_demo = page.locator(".nr-demo-shell")
        ontology_demo.wait_for(state="visible", timeout=30_000)
        assert "自然资源本体应用" in ontology_demo.inner_text()
        ontology_demo.get_by_text("识别 445 个变化地块", exact=False).wait_for(
            state="visible", timeout=30_000
        )
        ontology_demo.get_by_text("OKF 0.2 计算证明通过", exact=False).wait_for(
            state="visible", timeout=30_000
        )

        page.screenshot(
            path=str(ARTIFACT_DIR / "heping-review-chat-map.png"),
            full_page=True,
        )
        browser.close()


if __name__ == "__main__":
    main()
