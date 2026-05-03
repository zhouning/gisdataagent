"""Derive ablation slices from a Full-pipeline run by dropping specific intents."""
from __future__ import annotations

import json
from pathlib import Path


def derive_ablation(full_results_path: str | Path, drop_intent: str) -> dict:
    payload = json.loads(Path(full_results_path).read_text(encoding="utf-8"))
    records = [r for r in payload["records"] if r.get("intent") != drop_intent]
    n = len(records)
    ex = sum(r.get("ex", 0) for r in records) / n if n else 0.0
    return {"n": n, "execution_accuracy": ex, "drop_intent": drop_intent}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--full", required=True)
    p.add_argument("--drop", required=True)
    args = p.parse_args()
    print(json.dumps(derive_ablation(args.full, args.drop), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
