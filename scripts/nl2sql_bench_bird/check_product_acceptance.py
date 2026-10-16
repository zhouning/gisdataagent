"""Fail-closed gate for a complete, untouched 271-question product acceptance.

This reads persisted evidence only. It never generates SQL, changes a score,
or copies expected answers into the runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
GRADING = "bird-unordered-five-decimal-v1"
PRODUCT_INPUTS = "question text and authorized database only"


def source_data_errors(manifest: dict) -> list[str]:
    """Require a complete, internally consistent source-data fingerprint."""
    snapshot = manifest.get("source_data") or {}
    tables = snapshot.get("tables") or []
    if snapshot.get("version") != "ordered-row-json-md5-v1" or not tables:
        return ["Missing source data fingerprint taken before evaluation"]
    identities = set()
    for table in tables:
        if (not isinstance(table, dict) or not isinstance(table.get("db_id"), str)
                or not isinstance(table.get("table"), str) or not table["table"]
                or type(table.get("rows")) is not int or table["rows"] < 0
                or not re.fullmatch(r"[0-9a-f]{32}", str(table.get("ordered_row_md5", "")))):
            return ["Invalid source table fingerprint"]
        identity = (table["db_id"], table["table"])
        if identity in identities:
            return ["Duplicate source table fingerprint"]
        identities.add(identity)
    if {db for db, _ in identities} != set(manifest.get("databases", [])):
        return ["Source data fingerprint does not cover the evaluation databases"]
    expected = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    if snapshot.get("fingerprint_sha256") != expected:
        return ["Source data fingerprint digest differs from its table records"]
    return []


def assess(questions: list[dict], development: list[dict], manifest: dict,
           records: list[dict], *, expected_n: int = 271,
           expected_profile: str | None = None) -> dict:
    errors = source_data_errors(manifest)
    errors.extend(query_route_errors(manifest, records, expected_profile))
    expected = {q["question_id"] for q in questions}
    observed = [r["question_id"] for r in records]
    if len(questions) != expected_n or len(expected) != expected_n:
        errors.append("Independent benchmark must contain exactly 271 unique questions")
    if expected.intersection(q["question_id"] for q in development):
        errors.append("Independent benchmark overlaps the development questions")
    if len(observed) != expected_n or set(observed) != expected:
        errors.append("Incomplete or duplicate result records")
    if len(manifest.get("question_ids", [])) != expected_n or set(manifest.get("question_ids", [])) != expected:
        errors.append("Run manifest does not cover the complete independent benchmark")
    if manifest.get("product_inputs") != PRODUCT_INPUTS or manifest.get("grading_version") != GRADING:
        errors.append("Input or scoring contract differs from the fixed protocol")
    model = manifest.get("deployed_model") or {}
    errors.extend(model_evidence_errors(model))
    for r in records:
        qid = r["question_id"]
        if r.get("correct") not in (0, 1):
            errors.append(f"Invalid correctness value for question {qid}")
        if r.get("correct") and (r.get("prediction_status") != "ok" or r.get("gold_status") != "ok"
                                  or r.get("product_status") != "ok"):
            errors.append(f"Correctness claimed for an unexecuted/rejected query: {qid}")
        calls = r.get("llm_calls") or []
        if not calls:
            errors.append(f"Missing product model evidence: {qid}")
        else:
            errors.extend(f"{error}: {qid}" for error in model_call_errors(model, calls))
    correct = sum(r.get("correct") == 1 for r in records)
    required = (95 * expected_n + 99) // 100
    return {"passed": not errors and correct >= required, "protocol_valid": not errors,
            "planned_n": expected_n, "completed_n": len(records), "correct": correct,
            "required_correct": required,
            "accuracy": correct / expected_n if not errors else None,
            "errors": errors,
            "limitations": "Checks persisted records and protocol; does not independently re-execute results "
                           "or establish absence of model pretraining contamination. Hosted provider weights "
                           "cannot be independently frozen; Gemini identity uses official metadata and response model labels."}


def query_route_errors(manifest: dict, records: list[dict], expected_profile: str | None = None) -> list[str]:
    """Audit recorded routes; missing evidence cannot establish strict IR use.

    Historical manifests remain scoreable without asserting a route. New
    manifests and explicitly requested comparisons require per-question proof.
    """
    policy = manifest.get("query_policy")
    if policy is None and expected_profile is None:
        return []
    from data_agent.nl2sql_route_policy import QueryPolicyError, resolve_bird_query_policy
    try:
        expected = resolve_bird_query_policy(manifest.get("settings") or {}).evidence()
    except QueryPolicyError as exc:
        return ["Invalid frozen query route: " + str(exc)]
    if (policy != expected or (expected_profile is not None and expected["profile"] != expected_profile)):
        return ["Recorded query profile differs from the required frozen route"]
    errors = []
    for record in records:
        qid = record["question_id"]
        if record.get("query_policy") != policy:
            errors.append(f"Missing or different per-question query policy: {qid}")
        if not policy["strict_contract"]:
            continue
        ir = record.get("registered_ir") or {}
        # blocked_by_policy describes a refused fallback, never an SQL route.
        if ir.get("fallback") not in (None, "blocked_by_policy"):
            errors.append(f"Strict IR evaluation used SQL fallback: {qid}")
        if (record.get("product_status") == "ok" and
                (ir.get("status") != "compiled" or ir.get("strict_contract") is not True
                 or not isinstance(ir.get("query"), dict) or ir["query"].get("status") != "query"
                 or not isinstance(ir.get("compiled_plan"), dict))):
            errors.append(f"Executed query lacks strict IR compilation evidence: {qid}")
        if record.get("product_status") == "ok":
            plan = ir.get("compiled_plan") or {}
            if (not isinstance(plan, dict) or not record.get("sql")
                    or plan.get("compiled_statement") != record.get("sql")
                    or not isinstance(record.get("sql_parameters"), dict)
                    or plan.get("parameter_bindings") != record.get("sql_parameters")):
                errors.append(f"Executed SQL or parameters differ from the compiled IR plan: {qid}")
    return errors


def model_evidence_errors(model: dict) -> list[str]:
    if model.get("provider") == "ollama":
        return [] if model.get("digest") else ["Local Ollama artifact is not pinned"]
    if model.get("provider") == "gemini":
        metadata = model.get("metadata") or {}
        model_id = str(model.get("model") or "").removeprefix("models/")
        expected = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
        if (not model_id or model.get("identity_kind") != "official-provider-metadata-v1"
                or model.get("metadata_sha256") != expected
                or model.get("metadata_endpoint") != "https://generativelanguage.googleapis.com/v1beta/models/" + model_id
                or metadata.get("name") != "models/" + model_id or not metadata.get("version")
                or "generateContent" not in (metadata.get("supportedGenerationMethods") or [])):
            return ["Official Gemini model metadata is not pinned"]
        return []
    return ["Unsupported evaluation model provider"]


def model_call_errors(model: dict, calls: list[dict]) -> list[str]:
    errors = []
    for call in calls:
        if call.get("model") != model.get("model") or call.get("provider") != model.get("provider"):
            errors.append("Actual model route differs from the pinned model")
        if model.get("provider") == "gemini":
            no_response_failure = (call.get("status") == "failed"
                                   and call.get("response_received") is False)
            if (not no_response_failure and str(call.get("response_model") or "").removeprefix("models/")
                    != str(model.get("model") or "").removeprefix("models/")):
                errors.append("Gemini response model differs from the pinned model")
            if call.get("base_url") != "https://generativelanguage.googleapis.com/v1beta/openai":
                errors.append("Gemini call did not use the official API endpoint")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--query-profile", choices=("configured", "registered_ir_strict"), required=True)
    args = parser.parse_args()
    benchmark = ROOT / "benchmarks/bird_pg_unseen_official_2024.json"
    development = ROOT / "benchmarks/bird_pg_heldout_150.json"
    manifest = json.loads((args.run_dir / "manifest.json").read_text())
    records = [json.loads(s) for s in (args.run_dir / "records.jsonl").read_text().splitlines() if s.strip()]
    report = assess(json.loads(benchmark.read_text()), json.loads(development.read_text()), manifest, records,
                    expected_profile=args.query_profile)
    completion_path = args.run_dir / "completion.json"
    completion = json.loads(completion_path.read_text()) if completion_path.exists() else {}
    report["errors"].extend(completion_errors(completion, manifest, (args.run_dir / "records.jsonl").read_bytes()))
    if manifest.get("benchmark_sha256") != hashlib.sha256(benchmark.read_bytes()).hexdigest():
        report["errors"].append("Independent benchmark fingerprint differs")
    for name, digest in (manifest.get("code_sha256") or {}).items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            report["errors"].append(f"Runtime code fingerprint differs: {name}")
    if not manifest.get("code_sha256"):
        report["errors"].append("Missing frozen runtime code fingerprints")
    if report["errors"]:
        report.update(passed=False, protocol_valid=False, accuracy=None)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    raise SystemExit(0 if report["passed"] else 1)


def completion_errors(completion: dict, manifest: dict, raw_records: bytes) -> list[str]:
    errors = source_data_errors(manifest)
    source_digest = (manifest.get("source_data") or {}).get("fingerprint_sha256")
    if (completion.get("source_data_freeze_verified") is not True
            or completion.get("source_data_sha256") != source_digest):
        errors.append("Missing or invalid source data comparison after evaluation")
    fingerprint = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    if (completion.get("status") != "complete" or completion.get("runtime_freeze_verified") is not True
            or completion.get("manifest_sha256") != fingerprint
            or completion.get("records_sha256") != hashlib.sha256(raw_records).hexdigest()
            or completion.get("question_ids") != manifest.get("question_ids")
            or completion.get("n") != len(manifest.get("question_ids", []))):
        errors.append("Missing or invalid completion proof after the final runtime freeze check")
    return errors


if __name__ == "__main__":
    main()
