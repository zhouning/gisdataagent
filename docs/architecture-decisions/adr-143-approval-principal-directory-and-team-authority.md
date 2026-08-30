# ADR-143: Approval Principal Directory and Team Authority

**Status**: Accepted  
**Date**: 2026-08-04  
**Related**: ADR-103, ADR-140, ADR-141, ADR-142

## Context

ADR-142 made ApprovalCase routing authoritative, but its assignee validation only proved that a value
looked like `human:<id>`. It did not prove that the subject existed, was eligible to approve, was
currently available, or belonged to an assigned team.

The existing `agent_teams` and `agent_team_members` tables cannot supply this authority. They support
collaboration, are not tenant scoped, and do not model approval eligibility, availability, effective
time, delegation authority or versioned audit evidence. Reusing them would silently turn a social
workspace membership into decision authority.

## Options Considered

| Option | Benefit | Cost | Decision |
|---|---|---|---|
| Accept any syntactically valid username | No directory dependency | Phantom and unavailable approvers remain possible | Rejected |
| Reuse collaboration teams | Existing UI and tables | Wrong tenancy and governance semantics | Rejected |
| Query the identity provider during each decision | Current identity facts | External availability can break transaction atomicity | Rejected |
| Maintain a tenant-scoped approval projection with immutable changes | Atomic, auditable and fail closed | Requires directory synchronization | Chosen |

## Decision

Migration `121_approval_principal_directory` adds a dedicated approval directory to `gda_control`.

- `approval_principal` stores versioned `human:*` and `team:*` subjects. Eligibility requires active
  status, explicit approval permission, current availability and an effective validity window.
- `approval_team_member` stores effective-time human membership and whether a member may delegate for
  the team. A team is eligible only while it has at least one currently eligible member.
- Principal and membership changes use expected-version CAS functions, require a human actor and
  reason, and append immutable snapshot events. The gateway receives SELECT and function execution,
  never direct UPDATE or event INSERT rights.
- Assignment targets may be eligible humans or teams. A team member may decide for the team; only a
  member with `can_delegate` may move team ownership. The requester remains unable to approve the
  request.
- Every human terminal decision, including cancellation, requires a currently eligible directory
  principal. Workload cancellation semantics remain available to governed internal workflows where
  the ApprovalCase assignment does not reserve the decision for a human or team.
- `approval_assignment_actor_access` resolves `can_decide`, `can_delegate` and a stable reason from the
  same PostgreSQL authority used by transitions. The Inbox consumes this result instead of recreating
  membership logic in TypeScript.
- The platform API can list principals, CAS-upsert principals, list team membership versions and
  CAS-upsert memberships. Directory writes require a human administrator.
- The Inbox uses the current eligible directory as its human/team assignment selector. Free-form
  usernames are no longer the primary routing path.

## Rollout

This is a fail-closed authority change. Before migration 121 is enabled in an environment, the
identity/directory integration must register all current human approvers, team principals and active
memberships for each tenant.

The migration does not rewrite existing assignment history or invent eligibility records. An existing
assignee that is absent, inactive, unavailable or outside its validity window cannot issue a new human
decision until the directory is corrected. This is intentional and must be covered by deployment
preflight rather than bypassed with a fallback to collaboration tables.

## Trade-offs

- Availability and validity are authoritative once written, but this slice does not yet synchronize
  an enterprise IdP/HR directory, on-call schedule or leave calendar.
- Team membership is explicit and tenant local. Nested teams are not supported, avoiding recursive
  or ambiguous approval authority.
- There is no automatic assignment, load balancing, substitute selection, timeout escalation or
  reclamation yet. These policies must consume the directory rather than mutate it implicitly.
- Principal and membership events are queryable in PostgreSQL, while dedicated event-list API and
  administrative directory UI remain future operational surfaces.

## Consequences

- Phantom, inactive, unavailable, expired and empty-team assignees fail closed in PostgreSQL.
- Team decision and delegation authority is evaluated transactionally and is consistent with the
  access state shown in the Inbox.
- `scripts/certify_approval_case_assignment.py` now includes migration 121 and validates directory
  CAS, availability revocation, empty-team rejection, team member decision/delegation, membership
  version reads, tenant isolation, immutable evidence and least privilege with 34/34 checks passing
  in disposable PostgreSQL 16.
- Production readiness still requires enterprise directory/on-call synchronization, preflight drift
  detection, substitute and escalation policy, and operational metrics/alerts.
