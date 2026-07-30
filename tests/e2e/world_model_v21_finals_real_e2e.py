"""Real browser E2E for the Gemma 4 finals county planning prompt."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("GIS_AGENT_E2E_URL", "http://127.0.0.1:8000")
USERNAME = os.environ.get("GIS_AGENT_E2E_USER", "admin")
PASSWORD = os.environ.get("GIS_AGENT_E2E_PASSWORD", "")
PROMPT = (
    "@WorldModelV21 请使用 bishan 数据集运行一次快速县域 MPC 规划，"
    "完成硬约束审计，并仅在通过后保存已验证经验。"
)
ARTIFACT_DIR = Path("tests/e2e/artifacts/world_model_v21_finals_2026_07_30")

EXPECTED_TOOLS = [
    "world_model_v21_status",
    "paper9_inspect_resources",
    "paper9_recall_verified_episodes",
    "world_model_v21_pipeline",
    "paper9_audit_run",
    "paper9_commit_verified_episode",
]

REPORT_FILENAME = "County_Farmland_Planning_Report.pdf"


def _browse_user_files(page) -> list[dict]:
    payload = page.evaluate(
        """async () => {
            const response = await fetch('/api/user/files/browse?path=', {
                credentials: 'include',
            });
            if (!response.ok) {
                throw new Error(`file browse failed: HTTP ${response.status}`);
            }
            return response.json();
        }"""
    )
    return payload.get("entries", [])


def _wait_for_new_report(page, previous_modified: float) -> dict:
    handle = page.wait_for_function(
        """async ({filename, previousModified}) => {
            const response = await fetch('/api/user/files/browse?path=', {
                credentials: 'include',
            });
            if (!response.ok) return false;
            const payload = await response.json();
            const entry = (payload.entries || []).find(
                item => item.name === filename && item.type === 'pdf'
            );
            return entry && entry.size > 0 && entry.modified > previousModified
                ? entry
                : false;
        }""",
        arg={
            "filename": REPORT_FILENAME,
            "previousModified": previous_modified,
        },
        polling=500,
        timeout=180_000,
    )
    return handle.json_value()


def _duration_after_tool(response_text: str, tool_name: str) -> float:
    offset = response_text.index(tool_name)
    match = re.search(r"(\d+(?:\.\d+)?)\s*秒", response_text[offset : offset + 120])
    assert match, f"missing duration after {tool_name}"
    return float(match.group(1))


def _summary_duration(response_text: str, label: str) -> float:
    match = re.search(rf"{re.escape(label)}\s*(\d+(?:\.\d+)?)\s*秒", response_text)
    assert match, f"missing summary duration: {label}"
    return float(match.group(1))


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
        page.wait_for_timeout(5_000)

        box = page.get_by_placeholder("输入消息... (Enter 发送)")
        box.fill(PROMPT)
        box.press("Enter")

        response = page.locator(
            ".chat-message.assistant",
            has_text="县域耕地受控规划完成",
        ).last
        response.wait_for(timeout=240_000)
        response_text = response.inner_text()

        required_text = [
            "Gemma 4 + Google ADK",
            "6 次原生函数调用",
            "受控自主决策轨迹",
            "县域耕地空间优化引擎",
            "学习型状态转移模型集成 + MPC",
            "A / 数据准备：已复用（未重复执行）",
            "B / 样本生成：已复用（未重复执行）",
            "C / 状态转移模型训练：已复用（未重复执行）",
            "D / MPC 规划执行：完成",
            "完成双向置换：406 对",
            "耕地面积变化：1.9359 ha",
            "平均坡度变化：-0.6078%",
            "连片度变化：0.0202",
            "百亩方面积变化：35.13 ha",
            "硬约束校验：通过",
            "已验证经验库：已写入",
        ]
        for text in required_text:
            assert text in response_text, f"missing UI evidence: {text}"

        forbidden_text = [
            "Status:",
            "Adapter Version:",
            "Paper9 Package:",
            "Paper9 Algorithm:",
            "Tool 4",
            "Hard Gate",
            "Verified Memory",
            "Prepared Dir:",
            "Ensemble Dir:",
            "/app/bishan-runs",
            "/app/data_agent/uploads",
        ]
        for text in forbidden_text:
            assert text not in response_text, f"internal presentation leaked: {text}"

        positions = [response_text.index(tool) for tool in EXPECTED_TOOLS]
        assert positions == sorted(positions)
        tool_durations = {
            tool: _duration_after_tool(response_text, tool) for tool in EXPECTED_TOOLS
        }
        total_duration = _summary_duration(response_text, "总用时")
        planning_duration = _summary_duration(response_text, "MPC 规划")
        governance_duration = _summary_duration(response_text, "审计与经验提交")
        assert total_duration >= sum(tool_durations.values()) - 0.7
        assert abs(planning_duration - tool_durations["world_model_v21_pipeline"]) <= 0.2
        assert (
            abs(
                governance_duration
                - tool_durations["paper9_audit_run"]
                - tool_durations["paper9_commit_verified_episode"]
            )
            <= 0.3
        )
        (ARTIFACT_DIR / "response.txt").write_text(
            response_text + "\n",
            encoding="utf-8",
        )

        map_update = page.wait_for_function(
            """() => {
                const update = window.__lastMapUpdate;
                return update?.layers?.some(layer => layer.type === 'fgb')
                    ? update
                    : null;
            }""",
            timeout=60_000,
        ).json_value()
        assert len(map_update["layers"]) == 1
        layer = map_update["layers"][0]
        assert layer["type"] == "fgb"
        assert layer["category_column"] == "CHG_FLAG"
        assert set(layer["category_labels"].values()) == {
            "保持不变",
            "耕地 -> 林地",
            "林地 -> 耕地",
        }

        map_panel = page.locator(".map-3d-container")
        map_panel.wait_for(state="visible", timeout=60_000)
        page.wait_for_timeout(18_000)
        canvases = map_panel.locator("canvas")
        assert canvases.count() >= 1

        existing_report = next(
            (
                entry
                for entry in _browse_user_files(page)
                if entry.get("name") == REPORT_FILENAME
            ),
            None,
        )
        previous_modified = float((existing_report or {}).get("modified") or 0.0)
        report_started = time.monotonic()
        page.get_by_role("button", name="导出 PDF 报告").last.click()
        report_entry = _wait_for_new_report(page, previous_modified)
        report_duration = time.monotonic() - report_started
        assert page.get_by_text("生成失败:").count() == 0

        report_response = page.context.request.get(
            f"{BASE_URL}/api/user/files/{quote(REPORT_FILENAME)}"
        )
        assert report_response.ok, f"report download failed: {report_response.status}"
        report_bytes = report_response.body()
        assert report_bytes.startswith(b"%PDF-"), "downloaded report is not a PDF"
        assert len(report_bytes) == report_entry["size"]
        (ARTIFACT_DIR / REPORT_FILENAME).write_bytes(report_bytes)

        verification = {
            "status": "passed",
            "prompt": PROMPT,
            "public_agent_name": "县域耕地规划 Agent",
            "public_engine_name": "县域耕地空间优化引擎",
            "tool_trace": EXPECTED_TOOLS,
            "tool_durations_s": tool_durations,
            "total_duration_s": total_duration,
            "planning_duration_s": planning_duration,
            "governance_duration_s": governance_duration,
            "map_layer": {
                "name": layer["name"],
                "type": layer["type"],
                "category_column": layer["category_column"],
                "category_labels": layer["category_labels"],
                "canvas_count": canvases.count(),
            },
            "report": {
                "file_name": REPORT_FILENAME,
                "generation_duration_s": round(report_duration, 3),
                "size_bytes": report_entry["size"],
                "modified": report_entry["modified"],
                "download_verified": True,
            },
        }
        (ARTIFACT_DIR / "map_update.json").write_text(
            json.dumps(map_update, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (ARTIFACT_DIR / "verification.json").write_text(
            json.dumps(verification, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        chat = page.locator(".chat-messages")
        chat.evaluate("element => { element.scrollTop = 0; }")
        page.wait_for_timeout(500)
        page.screenshot(
            path=str(ARTIFACT_DIR / "response_top.png"),
            timeout=120_000,
        )
        browser.close()

    print(json.dumps(verification, ensure_ascii=False))


if __name__ == "__main__":
    main()
