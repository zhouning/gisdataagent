import importlib.util
import hashlib
import json
from pathlib import Path


def load_gate():
    path = Path(__file__).resolve().parents[1] / "scripts/nl2sql_bench_bird/check_product_acceptance.py"
    spec = importlib.util.spec_from_file_location("bird_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(correct=258):
    gate = load_gate()
    questions = [{"question_id": i} for i in range(271)]
    manifest = {"question_ids": list(range(271)), "product_inputs": gate.PRODUCT_INPUTS,
                "grading_version": gate.GRADING,
                "deployed_model": {"provider": "ollama", "model": "local", "digest": "artifact"}}
    tables = [{"db_id": "synthetic", "table": "observations", "rows": 4,
               "ordered_row_md5": "a" * 32}]
    manifest["databases"] = ["synthetic"]
    manifest["source_data"] = {"version": "ordered-row-json-md5-v1", "tables": tables,
        "fingerprint_sha256": hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()}
    records = [{"question_id": i, "correct": int(i < correct), "product_status": "ok",
                "prediction_status": "ok", "gold_status": "ok",
                "llm_calls": [{"provider": "ollama", "model": "local"}]} for i in range(271)]
    return gate, questions, manifest, records


def test_requires_at_least_258_of_271():
    for correct, passed in [(257, False), (258, True)]:
        gate, questions, manifest, records = fixture(correct)
        result = gate.assess(questions, [], manifest, records)
        assert result["passed"] is passed
        assert result["required_correct"] == 258


def test_partial_or_duplicated_perfect_scores_cannot_pass():
    gate, questions, manifest, records = fixture(271)
    for invalid in [records[:27], records[:-1] + [records[0]]]:
        result = gate.assess(questions, [], manifest, invalid)
        assert not result["passed"]
        assert result["accuracy"] is None


def test_development_overlap_and_label_input_are_rejected():
    gate, questions, manifest, records = fixture()
    assert not gate.assess(questions, [{"question_id": 1}], manifest, records)["passed"]
    manifest["product_inputs"] = "question and Gold SQL"
    assert not gate.assess(questions, [], manifest, records)["passed"]


def test_placeholder_and_unpinned_model_cannot_count_as_correct():
    gate, questions, manifest, records = fixture()
    records[0]["product_status"] = "rejected"
    assert not gate.assess(questions, [], manifest, records)["passed"]
    records[0]["product_status"] = "ok"
    records[0]["llm_calls"][0]["model"] = "different"
    assert not gate.assess(questions, [], manifest, records)["passed"]


def test_complete_question_count_does_not_replace_final_freeze_proof():
    import hashlib
    import json
    gate, _, manifest, records = fixture()
    raw = json.dumps(records).encode()
    assert gate.completion_errors({}, manifest, raw)
    marker = {"status": "complete", "runtime_freeze_verified": True,
              "source_data_freeze_verified": True,
              "source_data_sha256": manifest["source_data"]["fingerprint_sha256"],
              "manifest_sha256": hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest(),
              "records_sha256": hashlib.sha256(raw).hexdigest(),
              "question_ids": manifest["question_ids"], "n": 271}
    assert gate.completion_errors(marker, manifest, raw) == []
    assert gate.completion_errors(marker, manifest, raw + b'changed')


def test_missing_changed_incomplete_or_duplicate_source_fingerprints_cannot_pass():
    from copy import deepcopy
    gate, questions, manifest, records = fixture(271)
    for mode in ("absent", "changed", "scope", "duplicate", "invalid_count"):
        altered = deepcopy(manifest)
        if mode == "absent":
            altered.pop("source_data")
        elif mode == "changed":
            altered["source_data"]["tables"][0]["rows"] += 1
        elif mode == "scope":
            altered["databases"].append("missing_database")
        elif mode == "duplicate":
            altered["source_data"]["tables"] *= 2
        else:
            altered["source_data"]["tables"][0]["rows"] = True
        assert not gate.assess(questions, [], altered, records)["passed"], mode


def test_code_freeze_alone_does_not_prove_source_data_was_unchanged():
    gate, _, manifest, records = fixture()
    raw = json.dumps(records).encode()
    marker = {"status": "complete", "runtime_freeze_verified": True,
              "source_data_freeze_verified": True,
              "source_data_sha256": "different",
              "manifest_sha256": hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest(),
              "records_sha256": hashlib.sha256(raw).hexdigest(),
              "question_ids": manifest["question_ids"], "n": 271}
    assert gate.completion_errors(marker, manifest, raw) == [
        "Missing or invalid source data comparison after evaluation"]


def gemini_fixture():
    gate, questions, manifest, records = fixture()
    metadata = {"name": "models/gemini-4-argon", "version": "3.0",
                "supportedGenerationMethods": ["generateContent"]}
    manifest["deployed_model"] = {"provider": "gemini", "model": "gemini-4-argon", "digest": None,
        "identity_kind": "official-provider-metadata-v1", "metadata": metadata,
        "metadata_endpoint": "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-argon",
        "metadata_sha256": hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()}
    for record in records:
        record["llm_calls"] = [{"provider": "gemini", "model": "gemini-4-argon",
            "response_model": "gemini-4-argon",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"}]
    return gate, questions, manifest, records


def test_gemini_metadata_identity_uses_same_95_percent_gate():
    gate, questions, manifest, records = gemini_fixture()
    assert gate.assess(questions, [], manifest, records)["passed"]
    records[0]["correct"] = 0
    assert not gate.assess(questions, [], manifest, records)["passed"]


def test_gemini_missing_or_changed_metadata_invalidates_protocol():
    from copy import deepcopy
    gate, questions, manifest, records = gemini_fixture()
    for key in ("metadata", "metadata_sha256", "metadata_endpoint", "identity_kind"):
        altered = deepcopy(manifest)
        altered["deployed_model"].pop(key)
        assert not gate.assess(questions, [], altered, records)["protocol_valid"]
    manifest["deployed_model"]["metadata"]["version"] = "different"
    assert not gate.assess(questions, [], manifest, records)["protocol_valid"]


def test_gemini_missing_response_label_or_gateway_route_cannot_pass():
    from copy import deepcopy
    gate, questions, manifest, records = gemini_fixture()
    for field, value in (("response_model", None), ("response_model", "gemini-other"),
                         ("base_url", "https://gateway.invalid/v1"), ("provider", "ollama")):
        altered = deepcopy(records)
        altered[0]["llm_calls"][0][field] = value
        assert not gate.assess(questions, [], manifest, altered)["protocol_valid"]


def strict_fixture(correct=258):
    from data_agent.nl2sql_route_policy import resolve_bird_query_policy
    gate, questions, manifest, records = fixture(correct)
    manifest["settings"] = {"GDA_NL2SQL_QUERY_PROFILE": "registered_ir_strict"}
    policy = resolve_bird_query_policy(manifest["settings"]).evidence()
    manifest["query_policy"] = policy
    for record in records:
        record["query_policy"] = dict(policy)
        record["sql"] = "SELECT :filter_001"
        record["sql_parameters"] = {"filter_001": 1}
        record["registered_ir"] = {"status": "compiled", "strict_contract": True,
                                   "query": {"status": "query"}, "compiled_plan": {
                                       "compiled_statement": record["sql"], "parameter_bindings": record["sql_parameters"]}}
    return gate, questions, manifest, records


def test_strict_acceptance_requires_per_question_compilation_and_no_sql_fallback():
    from copy import deepcopy
    gate, questions, manifest, records = strict_fixture()
    assert gate.assess(questions, [], manifest, records, expected_profile="registered_ir_strict")["passed"]
    for key, value in (("fallback", "existing_sql_generator"), ("status", "disabled"),
                       ("strict_contract", False), ("query", None), ("compiled_plan", None)):
        altered = deepcopy(records)
        altered[0]["registered_ir"][key] = value
        assert not gate.assess(questions, [], manifest, altered)["protocol_valid"], key
    records[0].pop("query_policy")
    assert not gate.assess(questions, [], manifest, records)["protocol_valid"]


def test_strict_acceptance_binds_executed_sql_and_values_to_compiler_output():
    from copy import deepcopy
    gate, questions, manifest, records = strict_fixture()
    for field, value in (("sql", "SELECT 99"), ("sql_parameters", {"filter_001": 2}),
                         ("sql_parameters", None)):
        altered = deepcopy(records)
        altered[0][field] = value
        assert not gate.assess(questions, [], manifest, altered)["protocol_valid"]


def test_unsupported_queries_remain_in_accuracy_denominator():
    gate, questions, manifest, records = strict_fixture(257)
    for record in records[257:]:
        record.update(product_status="unsupported", prediction_status="unsupported",
                      registered_ir={"status": "unsupported", "strict_contract": True,
                                     "fallback": "blocked_by_policy"})
    result = gate.assess(questions, [], manifest, records, expected_profile="registered_ir_strict")
    assert result["protocol_valid"] and not result["passed"]
    assert result["accuracy"] == 257 / 271
    assert not gate.assess(questions, [], manifest, records[:257])["protocol_valid"]
    records[257]["correct"] = 1
    assert not gate.assess(questions, [], manifest, records)["protocol_valid"]


def test_missing_manifest_or_mismatched_frozen_route_cannot_claim_strict_result():
    gate, questions, manifest, records = fixture()
    assert not gate.assess(questions, [], manifest, records, expected_profile="registered_ir_strict")["protocol_valid"]
    gate, questions, manifest, records = strict_fixture()
    manifest["settings"]["GDA_NL2SQL_REGISTERED_IR"] = "0"
    assert not gate.assess(questions, [], manifest, records)["protocol_valid"]
