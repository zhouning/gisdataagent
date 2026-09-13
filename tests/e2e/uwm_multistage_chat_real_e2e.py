"""Real browser E2E for left-chat UWM multi-stage planning."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8000"
PROMPT = (
    "@UWM规划 请先展示沙坪坝区土湾街道及1阶邻域的当前输入状态，"
    "再对增绿降温、交通减排和公共服务三类动作进行2步多阶段城市干预规划，"
    "采用均衡的不确定性偏好"
)
ARTIFACT_DIR = Path("tests/e2e/artifacts/uwm_multistage_chat_2026-07-16")


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1200})
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.locator("#username").fill("admin")
        page.locator("#password").fill("admin123")
        page.get_by_role("button", name="登录").click()
        page.locator(".app-header").wait_for(state="visible", timeout=30000)
        page.wait_for_timeout(12000)

        box = page.get_by_placeholder("输入消息... (Enter 发送)")
        box.fill("@")
        mention = page.locator(".mention-item", has_text="@UWM规划").first
        mention.wait_for(state="visible", timeout=30000)
        page.screenshot(path=str(ARTIFACT_DIR / "00-mention-dropdown.png"), full_page=True)
        mention.click()
        assert box.input_value() == "@UWM规划 "
        box.fill(PROMPT)
        box.press("Enter")

        parsed = page.locator(".chat-message.assistant", has_text="Gemma4场景语义解析").last
        parsed.wait_for(timeout=60000)
        parsed_text = parsed.inner_text()
        for expected in [
            "gemma4-26b-ollama",
            "已真实调用",
            "沙坪坝区 · 土湾街道",
            "1阶空间邻域",
            "规划时域：2",
            "增加绿色/降温基础设施",
            "实施交通排放治理",
            "新增或改善社区公共服务",
            "不确定性偏好：balanced",
        ]:
            assert expected in parsed_text
        page.screenshot(path=str(ARTIFACT_DIR / "00b-gemma4-scenario-parse.png"), full_page=True)

        inspection = page.locator(".chat-message.assistant", has_text="UWM推演前状态体检").last
        inspection.wait_for(timeout=60000)
        text = inspection.inner_text()
        for expected in [
            "当前输入UWM的状态",
            "当前规划域：6个空间单元",
            "1017个状态节点、7932条空间关系",
            "本场景候选动作实例：9个",
            "新增或改善社区公共服务：5个候选实例",
            "尚未训练Simulator",
            "尚未执行未来推演",
            "23维输入 → 6维下一状态变化",
        ]:
            assert expected in text

        initial_map = page.wait_for_function(
            "() => window.__lastMapUpdate?.metadata?.view_mode === 'uwm_state_inspection_before_rollout' ? window.__lastMapUpdate : null",
            timeout=30000,
        ).json_value()
        assert initial_map["metadata"]["future_rollout_executed"] is False
        assert initial_map["metadata"]["candidate_action_count"] == 9
        assert len(initial_map["layers"]) == 1
        assert len(initial_map["layers"][0]["geojsonData"]["features"]) == 6
        (ARTIFACT_DIR / "01-state-inspection-map.json").write_text(
            json.dumps(initial_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        page.screenshot(path=str(ARTIFACT_DIR / "02-before-confirmation.png"), full_page=True)

        page.get_by_role("button", name="确认2步推演").last.click()
        result = page.locator(".chat-message.assistant", has_text="UWM多阶段城市干预规划完成").last
        result.wait_for(timeout=60000)
        result_text = result.inner_text()
        for expected in [
            "推荐行动序列",
            "主搜索想象动作：73次",
            "完整未来序列：64条",
            "第二步首选因状态写回发生切换：是",
            "23维输入 → 6维输出",
            "138个系数",
        ]:
            assert expected in result_text

        branch_map = page.wait_for_function(
            "() => window.__lastMapUpdate?.summary?.title === '场景3：第二步未来分叉' ? window.__lastMapUpdate : null",
            timeout=30000,
        ).json_value()
        assert len(branch_map["layers"]) == 2
        (ARTIFACT_DIR / "03-branch-map.json").write_text(
            json.dumps(branch_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        page.screenshot(path=str(ARTIFACT_DIR / "03b-result-actions.png"), full_page=True)

        page.get_by_role("button", name="查看当前世界").last.click()
        page.wait_for_function(
            "() => window.__lastMapUpdate?.summary?.title === '场景1：t0当前复合压力世界'",
            timeout=30000,
        )
        page.get_by_role("button", name="查看第一步传播").last.click()
        page.wait_for_function(
            "() => window.__lastMapUpdate?.summary?.title === '场景2：a1执行并写回t1'",
            timeout=30000,
        )
        page.get_by_role("button", name="查看最终轨迹").last.click()
        page.wait_for_function(
            "() => window.__lastMapUpdate?.summary?.title === '场景4：UWM两步干预轨迹'",
            timeout=30000,
        )
        page.get_by_role("button", name="查看运行审计").last.click()
        audit = page.locator(".chat-message.assistant", has_text="UWM运行审计").last
        audit.wait_for(timeout=30000)
        assert "训练数据性质" in audit.inner_text()
        assert "状态写回验证：True" in audit.inner_text()

        page.screenshot(path=str(ARTIFACT_DIR / "04-after-planning.png"), full_page=True)
        browser.close()


if __name__ == "__main__":
    main()
