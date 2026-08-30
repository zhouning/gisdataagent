# DataProduct Rollback Authority Handoff (2026-08-07)

## Delivered

- `data_product_registry.py` now requires exactly one `incident_id` or
  `rollback_approval_case_ref` for every new rollback.
- Incident authority must be an active resource-bound DataIncident for the
  product. Approval authority must be an unexpired approved human
  `data_product.rollback` ApprovalCase whose fingerprint and request context
  bind the exact current/target version pair.
- Migration 151 stores authority kind/ref/fingerprint on the immutable product
  event and rejects direct SQL rollback inserts through a tenant-aware trigger.
- The data-product rollback API accepts the two typed authority references.
- Certification entrypoint: `scripts/certify_data_product_rollback_authority.py`.

## Verification

- Product registry, ConsumerBinding, architecture release, migration runner and
  platform contract regression: 77 passed, 1 environment-gated PostgreSQL test
  skipped.
- Ruff, compileall and `git diff --check` pass for the touched slice.
- Disposable PostgreSQL 16 certification passed for Incident rollback, human
  ApprovalCase rollback, immutable authority evidence and direct SQL bypass
  rejection. Report:
  `.tmp/data-product-rollback-certification/report.json`; SHA-256:
  `5cc2d817ca3ef93e16ac5e5f5cadc54a2631851a1d49bc4a9bf2c005fdfb81ae`.
- Migration catalog: 151 migrations; fingerprint:
  `60bee34db38f6f52ed6c327059ea8e7c3f46a06001ecc9a1d59f04f86cbb4a0f`.

## Remaining boundary

Production Alertmanager/on-call delivery, Service Control Plane service-level
ConsumerBinding/SLO, provider conformance, HA/RPO/RTO and AR-0/AR-1/AR-2/AR-4
exit gates remain incomplete.
