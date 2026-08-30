# ADR-142: ApprovalCase Assignment and Delegation Authority

**Status**: Accepted  
**Date**: 2026-08-04  
**Related**: ADR-103, ADR-140, ADR-141

## Context

The Approval Inbox can expose and decide governed cases, but an open pool alone cannot express who is
accountable for a specific decision. Chat mentions, notification receivers and UI-only ownership are
not authoritative: they cannot prevent another operator from racing the assigned reviewer or prove a
delegation chain.

Assignment is routing, not approval. It may narrow the eligible decision actor, but it must never set
`ApprovalCase.status`, manufacture a verdict, or authorize the target resource action.

## Options Considered

| Option | Benefit | Cost | Decision |
|---|---|---|---|
| Keep every case in an open pool | No new state | No accountability or delegation evidence | Rejected |
| Store assignee only in request context | Small schema | Immutable request cannot represent reassignment | Rejected |
| Treat assignment as ApprovalCase status | One state machine | Conflates routing with verdict authority | Rejected |
| Separate current projection plus immutable events | CAS, audit and efficient Inbox reads | Adds one routing authority | Chosen |

## Decision

Migration `120_approval_case_assignment_authority` adds tenant-scoped
`approval_case_assignment` and append-only `approval_case_assignment_event` tables.

- A human administrator may assign, reassign or release a live pending case.
- The current human assignee may delegate to another human who is not the requester. Delegation depth
  is limited to five; administrative reassignment resets that depth.
- Every transition requires `expected_assignment_version` and a reason. Stale writes fail with a
  conflict and direct gateway table writes remain denied.
- Cases without an assignment retain the existing open-pool behavior. A released assignment returns
  to that open pool without deleting its routing history.
- While routing status is `assigned`, the database permits a terminal ApprovalCase decision only from
  the current assignee. This check is inside `transition_approval_case`, not only in API or UI code.
- A terminal ApprovalCase event closes the routing projection in the same transaction and appends a
  `closed` assignment event. Assignment history never becomes an ApprovalCase verdict.
- The API derives actor and assignee subject types from authenticated identities. Assign, reassign and
  release require the admin role; delegate additionally requires the database-verified current
  assignee.

## Trade-offs

- This slice originally admitted only individual human assignees. ADR-143 subsequently adds the
  governed membership resolver required for `team:*` decision principals.
- Releasing to an open pool is retained for backward compatibility. Deployments that require every
  case to be assigned can add a policy gate without changing the core state model.
- Assignment is per case and does not yet provide workload balancing, escalation timers or bulk
  routing. Those belong in the cross-case operations view.

## Consequences

- The platform can prove who owned a decision and how ownership moved before the verdict.
- Assignment races, unauthorized delegation and non-assignee decisions fail closed in PostgreSQL.
- `scripts/certify_approval_case_assignment.py` applies the relevant migrations to disposable
  PostgreSQL 16. Its original 19 routing checks remain in the 34-check certification extended by
  ADR-143.
- Absence/escalation policy and production operational dashboards remain future acceptance gates.
