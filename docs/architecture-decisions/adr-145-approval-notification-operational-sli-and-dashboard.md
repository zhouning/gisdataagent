# ADR-145: Approval Notification Operational SLI and Dashboard Provisioning

**Status**: Accepted

**Date**: 2026-08-04

**Related**: ADR-140, ADR-141, ADR-144

## Context

ADR-144 makes ApprovalCase notification workers scrapeable and alertable, but individual raw metrics
and alert rules are not a durable operating view. Operators still need stable, low-cost queries for
delivery success, worker availability, work-loop freshness and cycle latency. A dashboard JSON file
alone is also insufficient: its datasource, folder, immutable identity and actual Grafana loading
path must be testable.

Idle notification windows are normal. A success SLI that treats an empty window as zero would page or
mislead operators when there is simply no ApprovalCase traffic.

## Decision

- The canonical Prometheus rule file records seven operational series: healthy and discovered worker
  replicas, successful-cycle age, delivery success ratios over 30 minutes and 6 hours, delivery
  attempt rate by outcome, and notification-cycle P95 latency.
- Delivery success is attempt based. `delivered` is successful; `retrying` and `dead_lettered` are
  failed attempts. An idle window records 1 rather than manufacturing a failure. Availability and
  heartbeat age remain separate signals, so this convention cannot hide a stopped worker.
- `gda-approval-case-operations` is the immutable dashboard UID. The dashboard contains ten panels
  for fleet health, delivery SLI, freshness, latency, outcomes and firing ApprovalCase alerts. Every
  panel binds to a Prometheus datasource variable whose provisioned default UID is `gda-prometheus`.
- Grafana datasource and dashboard providers are versioned under `config/grafana/provisioning`.
  Prometheus URL injection uses `GDA_GRAFANA_PROMETHEUS_URL`; credentials are not stored in these
  files. Provisioned dashboards are read-only and live in the stable
  `gda-approval-operations` folder.
- The Kubernetes component generates `gis-agent-approval-notification-dashboard` from the canonical
  dashboard JSON and labels it `grafana_dashboard=1`. A cluster Grafana sidecar may discover it
  without introducing another operator-specific custom resource.
- The canonical rules and PrometheusRule CRD remain exactly equal under contract tests. Dashboard
  identity, panels, queries, provisioning and ConfigMap generation are also contract tested.

## Verification

- Prometheus 3.5.0 `promtool test rules` evaluates both the seven recording rules and all five alert
  scenarios, including the idle-window success convention.
- `scripts/rehearse_approval_grafana_provisioning.py` starts real Prometheus 3.5.0 and Grafana 11.6.0
  containers on a disposable network. It verifies the rule API, datasource health, search API,
  dashboard UID, folder, file-provisioned status, ten panels and cleanup.
- `scripts/rehearse_approval_observability_routing.py` continues to prove that the expanded rule file
  passes promtool and that the Alertmanager receiver filter is unchanged.
- `kubectl kustomize` renders the dashboard ConfigMap with the expected sidecar label and folder
  annotation.

## Consequences

- Clusters must configure their Grafana sidecar to watch the `gis-agent` namespace for
  `grafana_dashboard=1`, or mount the same dashboard through an equivalent reviewed mechanism.
- Long-term retention, SLO ownership and paging escalation remain environment responsibilities. The
  6-hour rule is a query accelerator and operating trend, not evidence that long-term storage exists.
- Real local provisioning proves binary and API interoperability. It does not prove staging or
  production deployment, enterprise identity, TLS, persistent Grafana storage, enterprise paging or
  multi-cluster dashboard aggregation.
