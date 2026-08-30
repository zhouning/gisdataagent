# AgentOps Discovery Observability

This optional package adds the Prometheus Operator `ServiceMonitor` for the
discovery worker's existing metrics Service. It is intentionally separate from
the core discovery sandbox because clusters without the
`servicemonitors.monitoring.coreos.com` CRD must still be able to deploy and
exercise the worker through its native `/metrics` endpoint.

Enable this package only after the Prometheus Operator CRD is installed:

```bash
kubectl apply -k k8s/optional/temporal-agentops-discovery-observability
```

The package does not install Prometheus, create a scrape credential, or prove
metrics collection. The core discovery deployment remains responsible for its
metrics HTTP endpoint and Service.
