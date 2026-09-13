from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FILES = ("overview.json", "evidence_assets.json", "financial_channels.json", "data_contracts.json", "calculation_gate.json", "map.json")
FORBIDDEN = {"npv", "irr", "payback", "roi", "affordability_score", "bankability_score", "investment_rank", "recommended_investment", "capital_budget", "operating_budget"}


def verify(root: Path):
    payloads = {name: json.loads((root / name).read_text()) for name in FILES}
    bundle_ids = {payload.get("bundle_id") for payload in payloads.values()}
    if len(bundle_ids) != 1 or None in bundle_ids:
        raise ValueError("bundle_mismatch")
    overview = payloads["overview.json"]
    assets = payloads["evidence_assets.json"]["evidence_assets"]
    channels = payloads["financial_channels.json"]["financial_channels"]
    gate_payload = payloads["calculation_gate.json"]
    if overview.get("fabricated_value_count") != 0 or FORBIDDEN & set(overview):
        raise ValueError("invalid_overview")
    if any(not asset.get("source_path") or asset.get("execution_status") == "observed_customer_financial_data" for asset in assets):
        raise ValueError("invalid_evidence_asset")
    if any(channel.get("status") != "unavailable" or channel.get("value") is not None for channel in channels.values()):
        raise ValueError("fabricated_financial_input")
    if gate_payload["calculation_gate"].get("status") != "closed" or any(value != "closed" for value in gate_payload["calculation_gate"]["mechanisms"].values()):
        raise ValueError("false_financial_calculation")
    if gate_payload["uwm_handoff_gate"].get("status") != "closed" or any(value is not None for value in gate_payload["financial_outputs"].values()):
        raise ValueError("fabricated_financial_output")
    digest = hashlib.sha256("".join((root / name).read_text() for name in FILES).encode()).hexdigest()
    return {"bundle_id": next(iter(bundle_ids)), "summary": overview["summary"], "fabricated_value_count": 0, "digest": "sha256:" + digest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), ensure_ascii=False))


if __name__ == "__main__":
    main()
