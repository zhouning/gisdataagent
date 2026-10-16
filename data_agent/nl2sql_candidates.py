"""Opt-in, bounded execution consensus over fully guarded product runs.

Agreement is an observed property of candidate results, never a probability of
correctness. No expected query, reference answer or benchmark annotation is
available to this module. Every candidate uses the ordinary product workflow.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from collections.abc import Callable
from contextvars import ContextVar
from datetime import date, datetime, time
from decimal import Decimal

from .user_context import (
    current_managed_agent_authorization, current_tenant_id, current_tool_categories,
    current_user_id, current_user_role,
)

_candidate_number: ContextVar[int | None] = ContextVar("nl2sql_candidate_number", default=None)
_HINTS = (
    "",  # First candidate retains the existing generation prompt.
    "\nIndependent generation focus: identify exactly the requested answer columns and "
    "what one output row represents before constructing SQL. Distinguish entities from "
    "their observations and categories from individual records. Measures used only to "
    "rank or filter are not answer columns. Use the full governed calculation and "
    "registered relationships; do not invent a field or change the question. Return SQL only.\n",
    "\nIndependent generation focus: derive the query from the question and the governed "
    "definitions. Verify every condition, code, unit and date scope. Check joins for "
    "multiplication of the requested entity, and distinguish extrema from explicit top K. "
    "Use the requested output order and multiplicity. Do not add helpful but unrequested "
    "outputs or guess missing definitions. Return SQL only.\n",
)


def candidates_enabled() -> bool:
    value = os.environ.get("GDA_NL2SQL_EXECUTION_CONSENSUS", "0").strip().casefold()
    if value in {"0", "false", "off", "no", ""}:
        return False
    if value in {"1", "true", "on", "yes"}:
        return True
    raise ValueError("GDA_NL2SQL_EXECUTION_CONSENSUS must be a boolean")


def in_candidate_run() -> bool:
    return _candidate_number.get() is not None


def candidate_generation_hint() -> str:
    index = _candidate_number.get()
    return _HINTS[index] if index is not None else ""


def _principal():
    return (current_user_id.get(), current_user_role.get(), current_tenant_id.get(),
            frozenset(current_tool_categories.get()),
            copy.deepcopy(current_managed_agent_authorization.get()))


def _cell(value) -> tuple:
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Nonfinite results cannot establish agreement")
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("Nonfinite results cannot establish agreement")
        # Exact numeric equality, independent of Decimal scale; no benchmark
        # rounding rule is imported into product candidate selection.
        value_text = format(number, "f")
        if "." in value_text:
            value_text = value_text.rstrip("0").rstrip(".")
        return ("number", value_text if number else "0")
    if isinstance(value, str):
        return ("text", value)
    if isinstance(value, (datetime, date, time)):
        return (type(value).__name__, value.isoformat())
    if isinstance(value, bytes):
        return ("bytes", value.hex())
    raise ValueError("Unsupported result type cannot establish agreement")


def result_fingerprint(columns: list[str], rows: list[tuple], truncated: bool) -> str | None:
    """Hash the complete unordered bag, keeping column order and duplicates.

    Aliases do not affect equality. Truncated and empty results cannot vote;
    coincidentally empty wrong queries would otherwise dominate a consensus.
    """
    if truncated or not rows:
        return None
    if any(len(row) != len(columns) for row in rows):
        raise ValueError("Result width differs from its columns")
    counts = Counter(json.dumps([_cell(value) for value in row], ensure_ascii=False,
                                separators=(",", ":")) for row in rows)
    value = json.dumps([len(columns), sorted(counts.items())], ensure_ascii=False,
                       separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def run_product_candidates(
    run_single: Callable[[], dict],
    read_result: Callable[[dict], tuple[list[str], list[tuple], bool]],
    check_authority: Callable[[], None],
) -> dict:
    """Run three candidates sequentially and select by complete-result agreement.

    read_result must be the authorized, read-only source adapter, never a
    preview from product JSON. No candidate can bypass guards or change the
    current principal. Without a majority, keep the first successful run.
    """
    if in_candidate_run():
        raise ValueError("Nested candidate selection is forbidden")
    principal = _principal()

    def authorized():
        if _principal() != principal:
            raise PermissionError("Candidate selection principal changed")
        check_authority()
        if _principal() != principal:
            raise PermissionError("Candidate selection principal changed")

    products, audit, all_calls = [], [], []
    groups = defaultdict(list)
    refusal = None
    for index in range(len(_HINTS)):
        authorized()
        token = _candidate_number.set(index)
        try:
            product = run_single()
        finally:
            _candidate_number.reset(token)
        authorized()
        products.append(product)
        calls = [{**call, "candidate_id": index} for call in product.get("llm_calls") or []]
        all_calls.extend(calls)
        entry = {"candidate_id": index, "status": product.get("status"),
                 "sql": product.get("sql") or "", "raw_sql": product.get("raw_sql"),
                 "sql_parameters": product.get("sql_parameters"),
                 "corrections": product.get("corrections") or [],
                 "result_fingerprint": None, "result_eligible": False}
        execution = product.get("execution") or {}
        if product.get("status") == "ok" and execution.get("status") == "ok" and entry["sql"]:
            try:
                columns, rows, truncated = read_result(product)
                authorized()
                fingerprint = result_fingerprint(columns, rows, truncated)
                entry.update(result_fingerprint=fingerprint, row_count=len(rows),
                             column_count=len(columns), truncated=truncated,
                             result_eligible=fingerprint is not None)
                if fingerprint is not None:
                    groups[fingerprint].append(index)
            except PermissionError:
                raise
            except Exception as exc:
                # Failed full-result verification cannot supply a vote.
                entry["verification_error_type"] = type(exc).__name__
        audit.append(entry)
        if product.get("error") == "policy_refusal":
            refusal = index
            break
    authorized()
    majority = next((indices for indices in groups.values() if len(indices) >= 2), None)
    successful = [i for i, product in enumerate(products)
                  if product.get("status") == "ok" and (product.get("execution") or {}).get("status") == "ok"]
    selected = refusal if refusal is not None else (majority[0] if majority else (successful[0] if successful else 0))
    result = dict(products[selected])
    result["llm_calls"] = all_calls
    result["candidate_selection"] = {
        "policy_version": "guarded-three-candidate-exact-bag-v1",
        "selected_candidate_id": selected, "attempted_candidates": len(products),
        "decision": "policy_refusal" if refusal is not None else ("execution_agreement" if majority else "first_successful_or_original"),
        "agreement_groups": [{"result_fingerprint": fingerprint, "candidate_ids": indices}
                             for fingerprint, indices in groups.items()],
        "candidates": audit,
        "limitations": "Agreement is not a correctness estimate; aliases are ignored, column order and duplicate counts are preserved. Empty or truncated results do not vote.",
    }
    return result
