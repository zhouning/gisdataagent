# ADR-357: AgentOps NetworkPolicy enforcement certification gate

## Status

Certification harness implemented; enforcement remains **blocked in the current
Docker Desktop kindnet cluster**. No NetworkPolicy enforcement or production
readiness is claimed.

## Context

The AgentOps sandbox already declares isolation policies for Temporal, PostgreSQL,
the execution worker and the discovery worker. Kubernetes accepting those objects
does not prove that the installed CNI drops traffic. The current cluster uses
`kindnet`, which exposes policy objects but does not enforce them.

## Decision

1. Add a reusable certification harness that inventories the cluster CNI before it
   mutates anything.
2. Treat Cilium, Calico, Antrea and kube-router as candidates that require an actual
   traffic probe; treat kindnet and unknown CNIs as a fail-closed block.
3. On a candidate CNI, create a disposable namespace with a server, an allowed client,
   a denied client and an ingress policy. The harness must observe allowed traffic
   succeeding and denied traffic failing, then delete the namespace.
4. A policy YAML/render check is not sufficient evidence for the AR-5 exit gate.

## Verification

The harness is [`certify_agentops_networkpolicy_enforcement.py`](../../scripts/certify_agentops_networkpolicy_enforcement.py).
Unit tests cover kindnet blocking, known-enforcing CNI detection and disposable probe
cleanup: `3 passed`.

The current cluster run observed `kindnet`, produced `mutation_performed=false`, and
correctly stopped before creating a namespace or Pod:

[`agentops_networkpolicy_enforcement_2026-08-30.json`](../reports/agentops_networkpolicy_enforcement_2026-08-30.json)

- `cni_inventory_observed=true`
- `cni_known_to_enforce_networkpolicy=false`
- `passed=false`
- `report_sha256=72bae1ccd05f465fd56510eba5c4a8acb66ceae5814cba6617e296bc47e1aa92`
- file SHA-256: `d6988bd5b1cf16b61d495cb07560002566301a39d879058e316564250d3108fd`

The failed result is intentional: it records an infrastructure blocker instead of
turning a non-enforcing development CNI into a false security claim.

## Limits and next gate

This ADR does not close NetworkPolicy enforcement, business-target lease takeover,
multi-node scheduling, identity rotation, HA/DR or RPO/RTO. The next execution must
run the same harness on a cluster with Cilium, Calico, Antrea or an equivalent
enforcing CNI, then extend the traffic probe to the actual discovery-to-Temporal and
discovery-to-control-PostgreSQL paths.
