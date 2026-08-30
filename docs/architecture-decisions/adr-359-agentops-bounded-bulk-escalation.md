# ADR-359: ApprovalCase bounded bulk escalation orchestration

## Status

Verified as a bounded orchestration slice. Batch approval, production paging,
enterprise on-call synchronization and a durable batch-operation ledger remain
open.

## Context

The ApprovalCase authority is intentionally per case: state-version CAS,
assignment/principal checks, tenant RLS and escalation idempotency all belong to
that boundary. Operators still need to schedule escalation for several cases in
one request, but a single all-or-nothing transaction would hide partial
successes and encourage bypassing the case authority.

## Decision

1. Add a typed batch request with one tenant, one actor, unique ApprovalCase
   references and at most 100 items.
2. Treat the batch as orchestration only. Execute each item by calling the
   existing `ApprovalCaseAuthority.schedule_sla_escalation()` method; do not
   write ApprovalCase or escalation tables directly.
3. Return one result per input item in request order. Each result is
   `scheduled`, `conflict`, `not_found`, `forbidden` or `rejected`, with the
   original authority error code for non-success outcomes.
4. Return a canonical request fingerprint and per-outcome counts. Partial
   success is an explicit result, not a rollback or a fabricated batch commit.
5. Keep durable idempotency at the case/stage authority. A durable batch
   operation ledger and retry/resume semantics are a separate follow-up and
   must not be implied by the request fingerprint.

## Implementation

- `data_agent/approval_case_batch.py`
- `ApprovalCaseBatchEscalationRequest`
- `ApprovalCaseBatchEscalationResult`
- `ApprovalCaseBatchEscalationResponse`
- `execute_approval_case_batch_escalation()`
- CapabilitySpec `agentops.approval-case.batch-escalate@1.0.0`
- HTTP `POST /api/platform/v1/approval-cases/escalation-batches` with the
  standard platform envelope and optional capability fingerprint guard.
- MCP tool `schedule_approval_case_batch_escalation`; deterministic SDK/CLI/
  TUI/Notebook clients use the same CapabilitySpec HTTP projection.
- HTTP and MCP enforce authenticated tenant and actor binding. A system or
  authority outage remains a request-level error; only case-scoped outcomes are
  represented as per-item partial success.

## Verification

The existing disposable PostgreSQL 16 certification now covers:

- two real cases scheduled in one request;
- one missing case reported independently as `not_found`;
- request-order preservation and per-case counts;
- successful batch items materialized by the existing two-stage SLA path;
- all previous SLA, tenant, gateway, suppression and verdict-neutral checks.

Report: [`agentops_approval_sla_escalation_2026-08-30.json`](../reports/agentops_approval_sla_escalation_2026-08-30.json)

- `schema=gda.agentops_approval_sla_escalation_certification.v3`
- `report_sha256=a95089e307e6b5ce87fe4e663e69b0c3e49a525fc95d0006bceee0e474cefc4c`
- file SHA-256: `c014543552ae0f724053033e56f023894703608daa43dd1e82485c7fd80d28f6`
- API/MCP contract regression: `data_agent/test_approval_case_batch_api.py`,
  `59 passed` across the batch, capability registry, and MCP gateway suites;
  Ruff passes for the new batch, capability, gateway, and batch API test files;
  `mcp_tool_registry.py` retains pre-existing unrelated lint findings, while
  `compileall` passes for the changed modules.
- AR-5/ApprovalCase/Capability/Gateway regression: `495 passed, 6 skipped`.
- Machine-readable entrypoint certification: [`agentops_approval_batch_capability_2026-08-30.json`](../reports/agentops_approval_batch_capability_2026-08-30.json).
  `report_sha256=71183827831c4f66f07b830256bd18a40d0007b84f82e8d2ed7e4f0a61e54d2a`;
  file SHA-256 `09545ec3d2434ca25539129a2747c308b4cba463fbe03686d488ac058b39585a`.

## Limits and next gate

This slice does not provide batch approval, a durable batch-operation ledger,
resume-after-client-loss semantics, production paging, enterprise on-call API
synchronization, UI inboxes, or production HA/RPO/RTO. Batch approval must be a
separate decision with explicit per-case authorization and outcomes.
