#!/usr/bin/env python3
"""Load non-approved compensation rule drafts from one persisted proposal."""

from __future__ import annotations

import argparse
import json

from data_agent.cross_store_projection_compensation_proposal_authority import (
    PostgresFederatedProjectionCompensationProposalStore,
)
from data_agent.cross_store_projection_compensation_rule_authority import (
    PostgresCustomerCompensationRuleAuthorityStore,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotently load technical_baseline_unreviewed customer-rule "
            "drafts for a persisted Chongqing federated compensation proposal."
        )
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    proposal = PostgresFederatedProjectionCompensationProposalStore(
        args.tenant_id
    ).current(args.run_id)
    if proposal is None:
        parser.error("no persisted compensation proposal exists for tenant/run")

    result = PostgresCustomerCompensationRuleAuthorityStore(
        args.tenant_id
    ).bootstrap_technical_baseline(proposal)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
