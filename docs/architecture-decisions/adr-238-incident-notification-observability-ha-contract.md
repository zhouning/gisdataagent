# ADR-238: Incident Notification Worker Observability and HA Deployment Contract

**Status**: Accepted  
**Date**: 2026-08-22  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-4

## Context

ADR-235/236/237 establish the authoritative GIS ServiceSLO -> DataIncident -> notification
outbox path and require a real Alertmanager 2xx provider receipt before a notification becomes
`done`. The remaining operational gap was the worker itself: a process could be alive while its
outbox cycles were failing or stalled, and the repository had no HA deployment, scrape, routing,
or network boundary contract for this worker.

## Decision

The Incident Notification Worker adopts the existing ApprovalCase notification worker pattern,
with incident-specific names and routing:

- `gda_incident_notification_operations_total{outcome}` counts `claimed`, `delivered`,
  `retrying`, `dead_lettered`, and `cycle_error` operations.
- `gda_incident_notification_cycle_duration_seconds` and
  `gda_incident_notification_last_success_timestamp_seconds` expose cycle latency and the
  last successful cycle heartbeat. Metrics are served only when
  `GDA_INCIDENT_NOTIFICATION_METRICS_PORT` is configured.
- `GDA_INCIDENT_NOTIFICATION_ROUTE_NAMESPACE` is validated as a Kubernetes DNS label and is
  emitted as the Prometheus `namespace` alert label. It is a routing label, not tenant authority.
- `k8s/observability/incident-notifications/` defines two replicas, rolling update with zero
  unavailable replicas, pod anti-affinity/topology spreading, a one-replica PDB, a metrics
  Service/ServiceMonitor, PrometheusRule, AlertmanagerConfig, and a restrictive NetworkPolicy.
- PostgreSQL credentials, tenant, Alertmanager URL, bearer token file, and on-call webhook URL
  are isolated in dedicated Secrets. URLs are never embedded in canonical configuration.
- Alertmanager routes `GDADataIncident` and `GDAIncidentNotification.*` only to the incident
  on-call receiver. ApprovalCase alerts have a separate receiver and group key.
- `config/prometheus/incident-notification-rules.yaml` is the canonical rule source; the
  Kubernetes PrometheusRule must remain semantically identical to it.

This does not add a second queue, incident table, routing database, or remediation controller.
The existing lease/attempt/receipt authority remains the only completion path.

## Evidence

- `data_agent/test_incident_notification_worker.py` and
  `data_agent/test_incident_observability_deployment.py` pass with the focused observability
  contract suite (`52 passed` including the existing worker/observability tests).
- `kubectl kustomize k8s/observability/incident-notifications` renders 8 Kubernetes documents
  (ServiceAccount, Deployment, Service, PDB, ServiceMonitor, PrometheusRule, AlertmanagerConfig,
  and NetworkPolicy).
- `scripts/rehearse_incident_observability_routing.py` ran with Alertmanager `v0.28.1` and
  Prometheus `v3.5.0`; report schema `gda.incident_observability_routing_rehearsal.v1`, SHA-256
  `3ae162260ed1ec9c99fb232acb05508a019a326c92c03e01b7865f4018fb814b`.
  The report verifies Alertmanager config, Prometheus rules, `GDADataIncident` ->
  `incident-oncall`, unrelated-alert isolation, secret-file URL loading, and disposable
  resource cleanup.

## Consequences and limits

Operators can detect worker disappearance, stalled cycles, cycle errors, retries, and dead letters,
and can deploy two lease-sharing replicas behind a controlled network boundary. The rehearsal is
local disposable evidence; it does not prove a production Kubernetes rollout, Alertmanager HA,
enterprise on-call integration, cross-region DR, RPO/RTO, capacity SLO, automatic remediation, or
exactly-once delivery. AR-4 remains `in_progress`.
