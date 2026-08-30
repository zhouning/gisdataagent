# ADR-144: Approval Notification Production Observability and On-call Routing

**Status**: Accepted

**Date**: 2026-08-04

**Related**: ADR-100, ADR-140, ADR-141, ADR-143

## Context

The ApprovalCase notification outbox, recovery authority and real local delivery rehearsal prove
durability and Alertmanager API interoperability. They do not make the worker discoverable by a
Prometheus Operator, detect a live process with a stalled work loop, route only approval alerts to an
on-call receiver, or keep receiver credentials out of deployment manifests.

Prometheus Operator also adds a namespace matcher to namespaced `AlertmanagerConfig` routes by
default. Direct alerts posted by the worker previously had no `namespace` label, so a syntactically
valid route could silently fail to match those alerts.

## Decision

- The worker accepts one optional `GDA_APPROVAL_NOTIFICATION_ROUTE_NAMESPACE`. It must be a valid
  Kubernetes DNS label and is added to the same stable labels for requested, expired and decided
  lifecycle updates. Kubernetes injects it from `metadata.namespace`; Compose leaves it unset.
- Every cycle that completes governed claim/delivery/ack processing updates
  `gda_approval_notification_last_success_timestamp_seconds`. Exceptions do not update the gauge.
  Together with scrape health, this distinguishes process unavailability from a stalled loop.
- `k8s/observability/approval-notifications` is an optional Prometheus Operator component. It runs two
  workers with rolling updates, pod anti-affinity, a PodDisruptionBudget, non-root/read-only security,
  a dedicated runtime Secret, a metrics Service, ServiceMonitor, PrometheusRule, AlertmanagerConfig
  and ingress/egress NetworkPolicy.
- The worker does not receive the general application Secret. PostgreSQL password, tenant, validated
  Alertmanager endpoint and bearer token come from `gis-agent-approval-notification-runtime`. The
  bearer token is mounted read-only as a file. URLs with embedded credentials remain rejected.
- The on-call webhook comes from the `gis-agent-approval-oncall` Secret. The canonical standalone
  Alertmanager configuration uses `url_file`; no receiver URL or token is committed.
- Alert rules cover all workers unavailable, successful cycles stalled, cycle errors, dead-letter
  events and retry surges. The canonical Prometheus rules and PrometheusRule CRD must remain exactly
  equal under contract tests.
- ApprovalCase lifecycle alerts and notification-operability alerts route to `approval-oncall`.
  Unrelated alerts remain on the parent receiver and cannot enter this route.

## Verification

- `promtool test rules` evaluates all five alert scenarios with Prometheus 3.5.0.
- `amtool check-config` validates the canonical route with Alertmanager 0.28.1.
- `scripts/rehearse_approval_observability_routing.py` starts a real Alertmanager, injects a local
  receiver through the secret file, posts one ApprovalCase alert and one unrelated control alert,
  and verifies that only the ApprovalCase alert reaches `approval-oncall`.
- Deployment contract tests verify HA, PDB, secret isolation, Downward API routing, metric scraping,
  canonical rule equality, secret receiver references and bounded network access.

## Consequences

- A cluster must install Prometheus Operator CRDs and select resources from the `gis-agent` namespace
  before applying this component.
- An external secret controller or an equivalent secure process must create both required Secrets.
- This decision provides a production-shaped deployment contract and real local protocol evidence.
  It does not claim that a staging or production cluster, enterprise on-call endpoint, TLS gateway,
  long-term Prometheus storage, dashboard or paging escalation has been verified.
