import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
QUERY = "请展示土地、农用地、建设用地、未利用地的本体层级"
ARTIFACT_DIR = Path("tests/e2e/artifacts/ontology-hierarchy")


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
            has_text="土地的领域类层级",
        )
        answer.wait_for(state="visible", timeout=120_000)
        answer_text = answer.inner_text()

        assert "农用地" in answer_text
        assert "建设用地" in answer_text
        assert "未利用地" in answer_text
        assert "耕地" in answer_text
        assert "AgriculturalLand" in answer_text
        assert "ConstructionLand" in answer_text
        assert "UnusedLand" in answer_text
        assert "本体 V2.0.1" in answer_text
        assert "分析完成。您可以下载相关文件" not in answer_text

        ontology_panel = page.locator(".ontology-workbench")
        ontology_panel.wait_for(state="visible", timeout=30_000)
        page.screenshot(
            path=str(ARTIFACT_DIR / "ontology-hierarchy-chat.png"),
            full_page=True,
        )
        browser.close()


if __name__ == "__main__":
    main()
