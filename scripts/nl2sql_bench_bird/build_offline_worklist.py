"""Build an immutable diagnostic worklist from saved evidence; no queries/models.

Gold SQL is retained only in benchmark artifacts. Annotations describe observed
static differences and investigation priorities, never runtime answer rules.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def digest(path: Path) -> dict:
    return {"path": str(path.resolve().relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def audit_metric_snapshot(metrics: list[dict], tables: list[dict]) -> dict:
    from data_agent.nl2sql_registered_ir import _logical_name, _scalar_formula_binding

    by_database = {}
    for table in tables:
        name = table["table_name"]
        database, bare = name.split(".", 1)
        fields = [{"semantic_field": _logical_name(c["column_name"], "field"),
                   "physical_field": c["column_name"], "data_type": c.get("pg_type") or c.get("data_type") or ""}
                  for c in table["columns"]]
        by_database.setdefault(database, []).append({"semantic_entity": database + "." + _logical_name(bare, "entity"),
                                                     "physical_table": name, "fields": fields})
    rows = []
    for metric in metrics:
        database = metric["domain"].split(".", 1)[0]
        binding = _scalar_formula_binding(metric["definition"], by_database.get(database, []))
        capability = ("aggregate_formula" if binding and binding.get("role") == "metric" else
                      "scalar_formula" if binding else "semantic_guidance_only_in_snapshot")
        rows.append({"metric_name": metric["metric_name"], "domain": metric["domain"],
                     "definition": metric["definition"], "unit": metric.get("unit"),
                     "snapshot_capability": capability, "binding": binding})
    return {"scope": "Expression binding against historical public metric and field-type snapshots only; not full query compilation or deployed coverage",
            "n": len(rows), "capabilities": dict(Counter(r["snapshot_capability"] for r in rows)), "metrics": rows}


def build(records: list[dict], annotations: dict, metrics: list[dict], tables: list[dict]) -> dict:
    ids = [r["question_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate question records")
    wrong = [r for r in records if not r["correct"]]
    notes = annotations["cases"]
    if {str(r["question_id"]) for r in wrong} != set(notes):
        raise ValueError("Every failed question must have exactly one annotation")
    cases = []
    for record in wrong:
        note = notes[str(record["question_id"])]
        if note["workstream"] not in annotations["workstreams"]:
            raise ValueError("Unknown investigation workstream")
        cases.append({**{k: record.get(k) for k in (
            "question_id", "db_id", "difficulty", "question", "product_status", "prediction_status",
            "failure_category", "sql", "sql_parameters", "gold_sql", "gold_execution_sql",
            "prediction_error", "prediction_row_count", "gold_row_count", "latency_ms")},
            **note, "verification_state": "Static SQL/evidence differences reviewed; data-level cause and corrected output remain unverified",
            "next_action": annotations["workstreams"][note["workstream"]]["action"],
            "exit_evidence": annotations["workstreams"][note["workstream"]]["exit_evidence"]})
    return {"created_at": datetime.now(timezone.utc).isoformat(),
            "scope": "Offline diagnosis of a development set; historical scores unchanged; no product rules keyed by question ID",
            "model_generation_calls": 0, "database_queries": 0,
            "baseline": {"n": len(records), "correct": sum(r["correct"] for r in records),
                         "accuracy": sum(r["correct"] for r in records) / len(records), "failed": len(cases)},
            "workstream_counts": dict(Counter(c["workstream"] for c in cases)),
            "workstreams": annotations["workstreams"], "cases": cases,
            "metric_snapshot_audit": audit_metric_snapshot(metrics, tables)}


def markdown(report: dict) -> str:
    base = report["baseline"]
    lines = ["# BIRD 离线错题工作清单", "", f"冻结基线：{base['correct']}/{base['n']}，准确率 {base['accuracy']:.0%}；全部 {base['failed']} 道失败题保留。",
             "本文件只记录历史证据和核验任务；静态SQL差异不等于已经证实根因。优先核验项互斥归类用于安排工作，一题可能同时涉及多个问题。",
             "本次模型生成调用0次、数据库查询0次；没有新的准确率。Gold只用于诊断，不进入产品。", "",
             "## 按核验任务分组", "", "| 工作项 | 题数 | 实现及核验任务 | 完成证据 |", "|---|---:|---|---|"]
    for key, n in report["workstream_counts"].items():
        stream = report["workstreams"][key]
        lines.append(f"| {key} | {n} | {stream['action']} | {stream['exit_evidence']} |")
    lines += ["", "## 逐题静态复核", "", "完整问题、生成SQL、原始Gold SQL、适配后的Gold SQL和历史行数见同名前缀的JSON、CSV文件。所有题当前均待数据级核验。", "",
              "| 题号 | 数据库 | 优先核验项 | 已观察到的差异 |", "|---:|---|---|---|"]
    for c in report["cases"]:
        lines.append(f"| {c['question_id']} | {c['db_id']} | {c['workstream']} | {c['observation'].replace('|', '/')} |")
    metric = report["metric_snapshot_audit"]
    lines += ["", "## 历史指标快照的表达式绑定能力", "",
              "使用公开指标快照和字段类型快照，调用当前产品表达式绑定器。此检查未调用实时登记库，未构造整条查询，也未验证关联、业务口径及检索选择。不能当作线上可回答率或准确率。", "",
              "| 快照绑定结果 | 指标数 |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in metric["capabilities"].items()]
    lines += ["", "无法绑定的表达式可能超出当前契约，或缺少匹配字段类型信息；详细定义逐项保存在JSON中。", "", "## 输入追溯", ""]
    lines += [f"- `{name}`：`{entry['path']}`，SHA-256 `{entry['sha256']}`" for name, entry in report["inputs"].items()]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    for name in ("records", "annotations", "metric-catalog", "inventory", "out-prefix"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    inputs = {name: getattr(args, name) for name in ("records", "annotations", "metric_catalog", "inventory")}
    outputs = [Path(str(args.out_prefix) + suffix) for suffix in (".json", ".csv", ".md")]
    if any(p.exists() for p in outputs) or any(p.resolve() == i.resolve() for p in outputs for i in inputs.values()):
        raise FileExistsError("Use a new output prefix; source and historical artifacts are immutable")
    records = [json.loads(line) for line in args.records.read_text().splitlines() if line.strip()]
    report = build(records, json.loads(args.annotations.read_text()),
                   json.loads(args.metric_catalog.read_text())["metrics"], json.loads(args.inventory.read_text())["tables"])
    report["inputs"] = {name: digest(path) for name, path in inputs.items()}
    report["inputs"].update({"binding_implementation": digest(ROOT / "data_agent/nl2sql_registered_ir.py"),
                             "diagnostic_builder": digest(Path(__file__))})
    columns = ["question_id", "db_id", "difficulty", "question", "workstream", "observation", "verification_state",
               "next_action", "exit_evidence", "product_status", "prediction_error", "sql", "gold_sql", "gold_execution_sql",
               "prediction_row_count", "gold_row_count", "latency_ms"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(report["cases"])
    contents = [json.dumps(report, ensure_ascii=False, indent=2) + "\n", "\ufeff" + buffer.getvalue(), markdown(report)]
    args.out_prefix.parent.mkdir(parents=True, exist_ok=True)
    for path, content in zip(outputs, contents):
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    print(json.dumps({"failed_questions": len(report["cases"]), "metrics": report["metric_snapshot_audit"]["capabilities"],
                      "model_calls": 0, "database_queries": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
