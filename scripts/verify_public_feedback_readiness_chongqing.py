from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FILES = ("overview.json", "capabilities.json", "feedback_channels.json", "data_contracts.json", "analysis_gate.json", "map.json")
FORBIDDEN = {"sentiment_score", "satisfaction_score", "complaint_hotspot", "public_preference", "issue_severity", "representative_prevalence", "policy_effect", "predicted_satisfaction"}


def verify(root: Path):
    payloads = {name: json.loads((root / name).read_text()) for name in FILES}; bundle_ids = {payload.get("bundle_id") for payload in payloads.values()}
    if len(bundle_ids) != 1 or None in bundle_ids: raise ValueError("bundle_mismatch")
    overview = payloads["overview.json"]; capabilities = payloads["capabilities.json"]["capabilities"]; channels = payloads["feedback_channels.json"]["feedback_channels"]; gate = payloads["analysis_gate.json"]["analysis_gate"]
    if overview.get("fabricated_value_count") != 0 or FORBIDDEN & set(overview): raise ValueError("invalid_overview")
    if any(not item.get("source_path") or item.get("status") == "observed_public_feedback" for item in capabilities): raise ValueError("invalid_capability")
    if any(channel.get("status") != "unavailable" or channel.get("value") is not None or channel.get("record_count") is not None for channel in channels.values()): raise ValueError("fabricated_feedback_observation")
    if gate.get("status") != "closed" or gate.get("uwm_observation_status") != "closed" or any(value != "closed" for value in gate["mechanisms"].values()): raise ValueError("false_feedback_analysis")
    digest = hashlib.sha256("".join((root / name).read_text() for name in FILES).encode()).hexdigest()
    return {"bundle_id": next(iter(bundle_ids)), "summary": overview["summary"], "fabricated_value_count": 0, "digest": "sha256:" + digest}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("root", type=Path); args = parser.parse_args(); print(json.dumps(verify(args.root), ensure_ascii=False))


if __name__ == "__main__": main()
