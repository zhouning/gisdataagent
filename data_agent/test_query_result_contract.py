import pandas as pd

from data_agent.query_result_contract import tabular_result_contract


def test_business_equivalence_ignores_aliases_row_order_and_numeric_noise():
    gold = pd.DataFrame(
        [["a", 1.0], ["b", 2.0000004]],
        columns=["category", "total"],
    )
    candidate = pd.DataFrame(
        [["b", 2], ["a", 1.0000001]],
        columns=["group_name", "aggregate_value"],
    )

    gold_contract = tabular_result_contract(gold)
    candidate_contract = tabular_result_contract(candidate)

    assert gold_contract["result_fingerprint"] != candidate_contract["result_fingerprint"]
    assert (
        gold_contract["equivalence_fingerprints"]["unordered_position_numeric6_fingerprint"]
        == candidate_contract["equivalence_fingerprints"]["unordered_position_numeric6_fingerprint"]
    )


def test_business_equivalence_preserves_source_nulls_and_column_position():
    expected = pd.DataFrame([[None, 1]], columns=["status", "count"])
    reordered = pd.DataFrame([[1, None]], columns=["count", "status"])

    expected_contract = tabular_result_contract(expected)
    reordered_contract = tabular_result_contract(reordered)

    assert (
        expected_contract["equivalence_fingerprints"]["unordered_position_numeric6_fingerprint"]
        != (
            reordered_contract["equivalence_fingerprints"][
                "unordered_position_numeric6_fingerprint"
            ]
        )
    )
