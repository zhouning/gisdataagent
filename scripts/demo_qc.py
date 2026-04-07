"""测绘质检端到端 Demo — 无 DB/LLM 依赖版本.

模拟 surveying_qc_standard 5 步标准质检流程:
  1. data_receive    — 数据概要
  2. data_preprocess — CRS 检查
  3. rule_audit      — 缺陷分类
  4. precision_verify — 拓扑 + 完整性 + 综合评分
  5. report_generate — 输出 JSON 报告

Usage:
    .venv/Scripts/python.exe scripts/demo_qc.py
    .venv/Scripts/python.exe scripts/demo_qc.py --file path/to/data.shp
"""

import argparse
import json
import sys
import io
import time
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Default test data
DEFAULT_FILE = str(
    ROOT / "01数据样例" / "04重庆市中心城区建筑物轮廓数据2021年" / "中心城区建筑数据带层高.shp"
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _header(step_num: int, title: str):
    print(f"\n{'='*60}")
    print(f"  Step {step_num}: {title}")
    print(f"{'='*60}")


def _elapsed(start: float) -> str:
    return f"{time.time() - start:.1f}s"


# ── Main ─────────────────────────────────────────────────────────────────


def run_demo(file_path: str):
    report = {"file": file_path, "steps": {}, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    total_start = time.time()

    # ── Step 1: data_receive ─────────────────────────────────────────
    _header(1, "数据接收 — 概要分析")
    t0 = time.time()
    try:
        from data_agent.toolsets.exploration_tools import describe_geodataframe
        summary = describe_geodataframe(file_path)
        report["steps"]["data_receive"] = {"status": "ok", "result": summary}

        # Print key info
        if isinstance(summary, dict):
            print(f"  记录数: {summary.get('row_count', 'N/A')}")
            print(f"  列数:   {summary.get('column_count', 'N/A')}")
            print(f"  CRS:    {summary.get('crs', 'N/A')}")
            print(f"  几何类型: {summary.get('geometry_type', 'N/A')}")
            if summary.get("warnings"):
                print(f"  警告: {summary['warnings']}")
        else:
            # May return string
            print(f"  {str(summary)[:500]}")
    except Exception as e:
        print(f"  ERROR: {e}")
        report["steps"]["data_receive"] = {"status": "error", "error": str(e)}
    print(f"  耗时: {_elapsed(t0)}")

    # ── Step 2: data_preprocess — CRS 检查 ───────────────────────────
    _header(2, "数据预处理 — CRS 一致性检查")
    t0 = time.time()
    try:
        from data_agent.toolsets.governance_tools import check_crs_consistency
        crs_result = check_crs_consistency(file_path, expected_epsg=4490)
        report["steps"]["crs_check"] = {"status": "ok", "result": crs_result}

        if isinstance(crs_result, dict):
            print(f"  当前 CRS: {crs_result.get('current_crs', 'N/A')}")
            print(f"  预期 EPSG: {crs_result.get('expected_epsg', 4490)}")
            print(f"  一致性: {'PASS' if crs_result.get('is_consistent') or crs_result.get('is_compliant') else 'FAIL - 需重投影'}")
        else:
            print(f"  {str(crs_result)[:500]}")
    except Exception as e:
        print(f"  ERROR: {e}")
        report["steps"]["crs_check"] = {"status": "error", "error": str(e)}
    print(f"  耗时: {_elapsed(t0)}")

    # ── Step 3: rule_audit — 缺陷分类 ────────────────────────────────
    _header(3, "规则审查 — 缺陷分类")
    t0 = time.time()
    try:
        from data_agent.toolsets.governance_tools import classify_defects
        defect_json = classify_defects(file_path, standard_id="gb_t_24356")
        defect_result = json.loads(defect_json) if isinstance(defect_json, str) else defect_json
        report["steps"]["defect_classification"] = {"status": "ok", "result": defect_result}

        if isinstance(defect_result, dict):
            print(f"  缺陷数: {defect_result.get('defect_count', 'N/A')}")
            print(f"  质量分: {defect_result.get('quality_score', 'N/A')}")
            print(f"  等级:   {defect_result.get('quality_grade', 'N/A')}")
            defects = defect_result.get("defects", [])
            if defects:
                print(f"  发现的缺陷类型:")
                for d in defects[:10]:
                    code = d.get("code", "?")
                    name = d.get("name", d.get("description", "?"))
                    sev = d.get("severity", "?")
                    cnt = d.get("count", d.get("affected_count", 1))
                    fix = "可自动修复" if d.get("auto_fixable") else "需人工处理"
                    print(f"    [{sev}] {code}: {name} (数量={cnt}, {fix})")
                if len(defects) > 10:
                    print(f"    ... 共 {len(defects)} 类缺陷")
        else:
            print(f"  {str(defect_result)[:500]}")
    except Exception as e:
        print(f"  ERROR: {e}")
        report["steps"]["defect_classification"] = {"status": "error", "error": str(e)}
    print(f"  耗时: {_elapsed(t0)}")

    # ── Step 4: precision_verify — 拓扑 + 完整性 + 综合评分 ──────────
    _header(4, "精度核验 — 拓扑 + 完整性 + 综合评分")
    t0 = time.time()

    # 4a: Topology
    topo_result = None
    try:
        from data_agent.toolsets.precision_tools import check_topology_integrity
        topo_raw = check_topology_integrity(file_path)
        topo_result = json.loads(topo_raw) if isinstance(topo_raw, str) and topo_raw.strip().startswith("{") else {"raw": str(topo_raw)[:1000]}
        report["steps"]["topology"] = {"status": "ok", "result": topo_result}

        if isinstance(topo_result, dict) and "score" in topo_result:
            print(f"  拓扑完整性分: {topo_result['score']}/100")
        else:
            print(f"  拓扑检查结果: {str(topo_result)[:300]}")
    except Exception as e:
        print(f"  拓扑检查 ERROR: {e}")
        report["steps"]["topology"] = {"status": "error", "error": str(e)}

    # 4b: Completeness
    comp_result = None
    try:
        from data_agent.toolsets.governance_tools import check_completeness
        comp_result = check_completeness(file_path)
        report["steps"]["completeness"] = {"status": "ok", "result": comp_result}

        if isinstance(comp_result, dict):
            total_rate = comp_result.get("overall_completeness", comp_result.get("completeness_rate"))
            print(f"  整体完整率: {total_rate}")
            fields = comp_result.get("field_stats", comp_result.get("fields", []))
            if isinstance(fields, list):
                nulls = [f for f in fields if f.get("null_rate", 0) > 0]
                if nulls:
                    print(f"  有空值的字段 ({len(nulls)}):")
                    for f in nulls[:5]:
                        print(f"    {f.get('name', '?')}: 空值率 {f.get('null_rate', 0):.1%}")
        else:
            print(f"  完整性结果: {str(comp_result)[:300]}")
    except Exception as e:
        print(f"  完整性检查 ERROR: {e}")
        report["steps"]["completeness"] = {"status": "error", "error": str(e)}

    # 4c: Governance score
    try:
        from data_agent.toolsets.governance_tools import governance_score
        audit = {}
        if isinstance(topo_result, dict):
            audit["topology"] = topo_result
        if isinstance(comp_result, dict):
            audit["completeness"] = comp_result
        if report["steps"].get("crs_check", {}).get("result"):
            audit["crs"] = report["steps"]["crs_check"]["result"]

        if audit:
            score_result = governance_score(audit)
            report["steps"]["governance_score"] = {"status": "ok", "result": score_result}

            if isinstance(score_result, dict):
                print(f"\n  ── 综合治理评分 ──")
                print(f"  总分: {score_result.get('total_score', 'N/A')}/100")
                print(f"  等级: {score_result.get('grade', 'N/A')}")
                dims = score_result.get("dimensions", {})
                if dims:
                    for dim, val in dims.items():
                        print(f"    {dim}: {val}")
    except Exception as e:
        print(f"  综合评分 ERROR: {e}")
        report["steps"]["governance_score"] = {"status": "error", "error": str(e)}

    print(f"  耗时: {_elapsed(t0)}")

    # ── Step 5: report_generate — 输出报告 ───────────────────────────
    _header(5, "报告生成")

    # Save JSON report
    report_path = ROOT / "scripts" / "demo_qc_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)

    total_time = time.time() - total_start
    print(f"  JSON 报告已保存: {report_path}")
    print(f"  总耗时: {total_time:.1f}s")

    # Summary
    ok_steps = sum(1 for s in report["steps"].values() if s.get("status") == "ok")
    total_steps = len(report["steps"])
    print(f"\n{'='*60}")
    print(f"  质检完成: {ok_steps}/{total_steps} 步成功")
    print(f"{'='*60}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测绘质检 Demo")
    parser.add_argument("--file", default=DEFAULT_FILE, help="数据文件路径")
    args = parser.parse_args()

    if not Path(args.file).exists():
        print(f"ERROR: 文件不存在: {args.file}")
        sys.exit(1)

    run_demo(args.file)
