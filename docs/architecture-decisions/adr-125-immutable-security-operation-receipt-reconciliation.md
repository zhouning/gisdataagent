# ADR-125: Security outcome reconciliation requires immutable completion receipts

- Status: accepted
- Date: 2026-08-02

## Context

ADR-124 requires an immutable `admitted` event before spatial anonymization and
an `outcome` event after execution. PostGIS DDL and the outcome append are not one
transaction, so anonymization can finish while the outcome append fails. An
attempt ID identifies the gap, but table existence alone does not prove which
attempt created the table or whether the expected row count and spatial index
were completed.

The output table comment was considered as a completion receipt. It was rejected
because an account with table DDL privileges can replace the comment. The
retention-based operational audit log is also not sufficient evidence, and a new
receipt database would duplicate tenant and operating authority.

## Options considered

| Option | Benefit | Cost |
|---|---|---|
| Infer success from table existence or operational audit | No new control-plane object | Cannot prove attempt binding, completeness or immutability |
| Store a receipt in the output-table comment | Receipt travels with the table | The table owner or DDL-capable account can rewrite it |
| Build a separate receipt control plane | Independent storage boundary | Duplicates tenant, identity, migration, backup and recovery authority |
| Extend `gda_control` with guarded receipts | Reuses forced RLS and the least-privilege gateway | Shares the PostgreSQL administrative trust boundary |

## Decision

Migration 111 adds `gda_control.security_operation_receipt`. A tenant may have
one receipt per attempt. Each receipt has a SHA-256 fingerprint, forced RLS and
an update/delete rejection trigger. The runtime gateway can select receipts and
execute guarded record/verify functions, but cannot directly insert, update or
delete receipt rows.

`record_security_operation_receipt(...)` accepts only the spatial anonymization
receipt contract in this slice. Before inserting it, the database verifies:

1. the transaction-local tenant matches the receipt tenant;
2. a matching admitted event exists for the same tenant, attempt, action and
   resource;
3. no outcome event already exists;
4. source and output identifiers reconstruct the admitted resource reference;
5. the output table exists and its actual row count matches the receipt; and
6. the named GiST index exists and is valid and ready.

Spatial polygon and point anonymization record this receipt after the output
table and index are complete. The receipt includes tenant, attempt, source,
output, data type, classification level, row count and spatial index. Existing
callers without security context keep their previous behavior and do not create
a security receipt.

The reconciler scans admitted events without outcomes. It may preview candidates,
but apply mode only appends `outcome/success` for `data_anonymize` when the
control-plane receipt exactly matches the admission. Re-identification
verification has no durable result artifact in this slice and always remains
`manual_review`. Apply requires a single attempt ID through the administrator API;
the CLI supports preview or apply and can be invoked by an external scheduler.

## Verification

`scripts/certify_security_event_reconciliation.py` applies migrations 092, 094,
110 and 111 in an automatically removed PostgreSQL 16 container. Its 14 checks
cover a real 12-row output table, a real GiST index, guarded and idempotent
receipt recording, success reconciliation, outcome evidence linkage, replay
idempotency, mismatch and verification manual review, tenant isolation, security
event chain integrity and receipt fingerprint verification.

The focused Python regression covers the receipt contract, ledger adapter,
reconciler, administrator routes and both spatial anonymization implementations.

## Trade-offs and boundary

PostGIS DDL, receipt recording and outcome append still span separate
transactions. A crash can occur before receipt recording, and an output table can
change after a valid receipt was recorded. The receipt proves the checked state
at recording time; it is not a perpetual checksum of the output data. Moving the
spatial operation behind a durable command/outbox or database-owned procedure is
the revisit trigger for atomic execution evidence.

The receipt fingerprint and immutable trigger are not an external trust anchor.
A PostgreSQL superuser remains inside the shared trust boundary. Production
compliance still requires external hash anchoring or WORM export, separate
retention authority, alerting and backup/restore verification.

This decision does not deliver full tenant ownership, purpose, column, row,
spatial and temporal policy, encryption and key rotation, release security gates,
or durable re-identification verification results. It does not complete AR-3,
AR-4, the full data-security lifecycle or the next-generation Data Platform.

Migration 111 may only be applied by the migration authority in an explicitly
selected environment. This decision does not authorize migration of the shared
development database.
