"""Run a frozen product evaluation using project credentials and explicit online settings."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path)
    parser.add_argument("--ids")
    parser.add_argument("--budget-policy", type=Path, required=True)
    parser.add_argument("--budget-ledger", type=Path, required=True)
    parser.add_argument("--query-profile", choices=("configured", "registered_ir_strict"), required=True,
                        help="Must match the frozen public settings before model calls")
    parser.add_argument("--preflight-only", action="store_true",
                        help="Validate the frozen runtime and route without loading credentials or calling a model")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from verify_runtime_freeze import verify_runtime_freeze
    from data_agent.nl2sql_route_policy import validate_evaluation_profile

    preflight = verify_runtime_freeze(ROOT)
    raw_settings = (ROOT / "public_settings.json").read_bytes()
    preparation = json.loads((ROOT / "freeze_preparation.json").read_text())
    if preparation["nonpython_sha256"].get("public_settings.json") != hashlib.sha256(raw_settings).hexdigest():
        raise RuntimeError("Public settings must be declared in the frozen resources")
    settings = json.loads(raw_settings)
    if settings.get("GDA_LLM_PROVIDER") != "gemini":
        raise RuntimeError("Frozen settings must select Gemini")
    preflight["query_policy"] = validate_evaluation_profile(settings, args.query_profile)
    (ROOT / "preflight_verification.json").write_text(json.dumps(preflight, indent=2) + "\n")
    print("PRE-MODEL FREEZE VERIFIED", flush=True)
    if args.preflight_only:
        print(json.dumps({"status": "preflight_only", "model_calls": 0,
                          "query_policy": preflight["query_policy"]}), flush=True)
        return
    load_dotenv(args.credentials_dir / ".env", override=True)
    load_dotenv(args.credentials_dir / ".bird.env", override=True)
    # Match the application's project credential precedence, avoiding an old
    # inherited key that load_dotenv(override=False) would silently preserve.
    key = dotenv_values(args.credentials_dir / ".env").get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Project GEMINI_API_KEY is missing")
    os.environ["GEMINI_API_KEY"] = key
    prefixes = ("NL2SQL_", "GDA_NL2SQL_", "GDA_LLM_", "GDA_OLLAMA_", "GDA_GEMINI_")
    for name in list(os.environ):
        if name.startswith(prefixes) and not name.endswith(("_KEY", "_TOKEN")):
            os.environ.pop(name)
    os.environ.update(settings)
    from data_agent.model_gateway import apply_gemini_transport_policy
    apply_gemini_transport_policy()
    from product_manifest import public_settings
    if public_settings() != settings:
        raise RuntimeError("Public runtime settings differ from the frozen configuration")
    evaluator = ROOT / "scripts/nl2sql_bench_bird/eval_product_source.py"
    sys.argv = [str(evaluator), "--out-dir", str(args.out_dir)]
    sys.argv += ["--budget-policy", str(args.budget_policy), "--budget-ledger", str(args.budget_ledger)]
    if args.ids:
        sys.argv += ["--ids", args.ids]
    if args.benchmark:
        sys.argv += ["--benchmark", str(args.benchmark)]
    runpy.run_path(str(evaluator), run_name="__main__")
    postflight = verify_runtime_freeze(ROOT)
    (ROOT / "postflight_verification.json").write_text(json.dumps(postflight, indent=2) + "\n")
    print("POST-MODEL FREEZE VERIFIED", flush=True)


if __name__ == "__main__":
    main()
