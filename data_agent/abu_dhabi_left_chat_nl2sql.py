"""Shared execution admission for Abu Dhabi NL2SQL in the left chat."""

from __future__ import annotations

from typing import Any, Literal

Scope = Literal["liveability", "makani", "federated"]


def apply_left_chat_execution_admission(
    scope: Scope,
    question: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return the product admission and a non-executing rejection when blocked."""

    from .api.abu_dhabi_nl2sql_product_routes import (
        _admission_rejection,
        _execution_admission,
    )

    admission = _execution_admission(scope, question)
    if admission.get("runtime_admitted"):
        return admission, None
    return admission, _admission_rejection(scope, admission)


__all__ = ["Scope", "apply_left_chat_execution_admission"]
