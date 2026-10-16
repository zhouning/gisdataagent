"""Preserve a completed product run only after verifying its frozen evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from check_product_acceptance import completion_errors, model_evidence_errors, model_call_errors
from verify_runtime_freeze import verify_runtime_freeze


def verify_run(run_dir: Path, runtime_root: Path) -> dict:
    dependency_verification = (verify_runtime_freeze(runtime_root)
                               if (runtime_root / "dependency_freeze.json").exists() else None)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    raw = (run_dir / "records.jsonl").read_bytes()
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    completion = json.loads((run_dir / "completion.json").read_text())
    errors = completion_errors(completion, manifest, raw)
    errors.extend(model_evidence_errors(manifest.get("deployed_model") or {}))
    for record in records:
        errors.extend(model_call_errors(manifest.get("deployed_model") or {}, record.get("llm_calls") or []))
    ids = [record.get("question_id") for record in records]
    if ids != manifest.get("question_ids") or len(ids) != len(set(ids)):
        errors.append("Result records differ from the frozen question sequence")
    if any(type(record.get("correct")) is not int or record["correct"] not in (0, 1) for record in records):
        errors.append("Invalid correctness values")
    code = manifest.get("code_sha256") or {}
    if not code:
        errors.append("Missing runtime fingerprints")
    for name, digest in code.items():
        path = (runtime_root / name).resolve()
        if (not path.is_relative_to(runtime_root.resolve()) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            errors.append(f"Frozen code differs: {name}")
    benchmark_name = manifest.get("benchmark") or ""
    benchmark = (runtime_root / "benchmarks" / benchmark_name).resolve()
    if (not benchmark_name or not benchmark.is_relative_to((runtime_root / "benchmarks").resolve())
            or not benchmark.is_file()
            or hashlib.sha256(benchmark.read_bytes()).hexdigest() != manifest.get("benchmark_sha256")):
        errors.append("Benchmark file differs from its frozen fingerprint")
    if errors:
        raise ValueError("; ".join(errors))
    correct = sum(record["correct"] for record in records)
    return {"protocol_verified": True, "n": len(records), "correct": correct,
            "dependency_verification": dependency_verification,
            "execution_accuracy": correct / len(records) if records else None,
            "valid_sql": sum(record.get("prediction_status") == "ok" for record in records),
            "code_files_verified": len(code),
            "manifest_sha256": completion["manifest_sha256"],
            "records_sha256": completion["records_sha256"],
            "source_data_sha256": completion["source_data_sha256"],
            "independent_acceptance": False}


def preserve_dependencies(runtime_root: Path, destination: Path) -> dict | None:
    """Preserve only declared runtime files, then verify the copied snapshot.

    Credentials and undeclared files are never copied from the runtime root.
    A second verification of the copy detects changes during preservation.
    """
    if not (runtime_root / "dependency_freeze.json").exists():
        return None
    original = verify_runtime_freeze(runtime_root)
    dependencies = json.loads((runtime_root / "dependency_freeze.json").read_text())
    preparation = json.loads((runtime_root / "freeze_preparation.json").read_text())
    names = set(dependencies) | set(preparation["nonpython_sha256"])
    if any(Path(name).name == ".env" or Path(name).name.endswith(".env")
           or Path(name).name.startswith(".env.") for name in names):
        raise ValueError("Environment credential files cannot be preserved")
    target_root = destination / "frozen_dependencies"
    if target_root.exists():
        raise FileExistsError("Frozen dependency destination already exists")
    for name in sorted(names):
        target = target_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runtime_root / name, target)
    for name in ("dependency_freeze.json", "freeze_preparation.json"):
        shutil.copy2(runtime_root / name, target_root / name)
        shutil.copy2(runtime_root / name, destination / name)
    copied = verify_runtime_freeze(target_root)
    if copied != original:
        raise ValueError("Preserved dependency verification differs from the original")
    for name in ("public_settings.json", "preflight_verification.json", "postflight_verification.json"):
        if (runtime_root / name).is_file():
            shutil.copy2(runtime_root / name, destination / name)
    report = {**copied, "copied_declared_files": len(names), "credentials_copied": False}
    (destination / "dependency_preservation_verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    report = verify_run(args.run_dir, args.runtime_root)
    # An existing result can never be replaced by a later score.
    if args.destination.exists():
        raise FileExistsError("Destination already exists; original results are immutable")
    shutil.copytree(args.run_dir, args.destination)
    manifest = json.loads((args.destination / "manifest.json").read_text())
    for name in manifest["code_sha256"]:
        target = args.destination / "frozen_code" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.runtime_root / name, target)
    benchmark = manifest["benchmark"]
    target = args.destination / "frozen_code" / "benchmarks" / benchmark
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.runtime_root / "benchmarks" / benchmark, target)
    preserved = preserve_dependencies(args.runtime_root, args.destination)
    if preserved:
        report["dependency_preservation"] = preserved
    (args.destination / "persistence_verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
