"""Register MetricFlow warehouse models for BIRD schemas.

Defines fact/dimension roles, entity keys, and measures for BIRD benchmark
schemas so that the NL2SQL grounding pipeline can inject join-path hints.

Usage:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/nl2sql_bench_bird/register_warehouse_models.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from data_agent.semantic_model import SemanticModelStore  # noqa: E402

# ---------------------------------------------------------------------------
# debit_card_specializing — the schema with most BIRD benchmark failures
# ---------------------------------------------------------------------------

DEBIT_CARD_MODELS = [
    {
        "name": "bird_debit_card_specializing.customers",
        "description": "Customer dimension table — segment and currency attributes",
        "source_table": "bird_debit_card_specializing.customers",
        "entities": [{"name": "CustomerID", "type": "primary", "column": "customerid"}],
        "dimensions": [
            {"name": "segment", "type": "categorical", "column": "segment"},
            {"name": "currency", "type": "categorical", "column": "currency"},
        ],
        "measures": [],
        "metrics": [],
    },
    {
        "name": "bird_debit_card_specializing.yearmonth",
        "description": "Monthly consumption fact table — one row per customer per month",
        "source_table": "bird_debit_card_specializing.yearmonth",
        "entities": [{"name": "CustomerID", "type": "foreign", "column": "customerid"}],
        "dimensions": [
            {"name": "date", "type": "time", "column": "date"},
        ],
        "measures": [
            {"name": "Consumption", "agg": "sum", "column": "consumption"},
        ],
        "metrics": [
            {"name": "total_consumption", "type": "simple", "measure": "Consumption"},
            {"name": "avg_consumption", "type": "derived", "measure": "Consumption"},
        ],
    },
    {
        "name": "bird_debit_card_specializing.transactions_1k",
        "description": "Transaction fact table — amount and price per transaction",
        "source_table": "bird_debit_card_specializing.transactions_1k",
        "entities": [
            {"name": "CustomerID", "type": "foreign", "column": "customerid"},
            {"name": "GasStationID", "type": "foreign", "column": "gasstationid"},
            {"name": "ProductID", "type": "foreign", "column": "productid"},
        ],
        "dimensions": [
            {"name": "date", "type": "time", "column": "date"},
        ],
        "measures": [
            {"name": "Amount", "agg": "sum", "column": "amount"},
            {"name": "Price", "agg": "avg", "column": "price"},
        ],
        "metrics": [
            {"name": "total_amount", "type": "simple", "measure": "Amount"},
            {"name": "avg_price", "type": "derived", "measure": "Price"},
        ],
    },
    {
        "name": "bird_debit_card_specializing.gasstations",
        "description": "Gas station dimension table — country and segment attributes",
        "source_table": "bird_debit_card_specializing.gasstations",
        "entities": [{"name": "GasStationID", "type": "primary", "column": "gasstationid"}],
        "dimensions": [
            {"name": "country", "type": "categorical", "column": "country"},
            {"name": "segment", "type": "categorical", "column": "segment"},
        ],
        "measures": [],
        "metrics": [],
    },
    {
        "name": "bird_debit_card_specializing.products",
        "description": "Product dimension table — product description",
        "source_table": "bird_debit_card_specializing.products",
        "entities": [{"name": "ProductID", "type": "primary", "column": "productid"}],
        "dimensions": [
            {"name": "description", "type": "categorical", "column": "description"},
        ],
        "measures": [],
        "metrics": [],
    },
]


def _model_to_yaml(model: dict) -> str:
    """Convert a model dict to YAML text suitable for SemanticModelStore.save()."""
    return yaml.dump(
        {"semantic_models": [model]},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def main() -> int:
    store = SemanticModelStore()
    ok, fail = 0, 0
    for model in DEBIT_CARD_MODELS:
        name = model["name"]
        yaml_text = _model_to_yaml(model)
        result = store.save(name, yaml_text, description=model.get("description", ""), created_by="bird_benchmark")
        if result:
            print(f"  [OK] {name} (id={result})")
            ok += 1
        else:
            print(f"  [FAIL] {name}", file=sys.stderr)
            fail += 1
    print(f"\nDone: {ok} saved, {fail} failed.")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
