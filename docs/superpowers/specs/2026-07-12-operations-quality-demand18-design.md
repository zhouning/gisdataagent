# Operations and Service Quality Evidence Demand 18 Design

**Date:** 2026-07-12  
**Branch:** `feat/operations-quality-demand18`  
**Product:** 运维与服务质量证据（需求18）

## 1. Objective

Implement demand 18 as three separated views:

```text
platform_operations_evidence
customer_sla_ticket_readiness
operations_uwm_readiness
```

The product inventories real platform observability, quality, workflow and alert capabilities; defines authoritative customer SLA, ticket and asset-lifecycle contracts; and exposes a fail-closed operations-world-model gate.

It does not claim customer contractual SLA compliance, service availability, incident performance, root cause, maintenance effectiveness or future failure risk.

## 2. Platform Operations Evidence

Supported capability categories:

```text
structured_logging
trace_context
pipeline_trace
api_metrics
prometheus_metrics
workflow_status
quality_rule_execution
quality_trends
alert_engine
database_pool_metrics
llm_invocation_metrics
agent_run_logs
bundle_availability_checks
fail_closed_product_gates
```

Each capability record includes evidence paths, API or module reference, observed-versus-contract status, limitations and maximum supported claim.

A capability implementation is not an observed operational result. Source code presence does not establish production use or service quality.

## 3. Customer SLA and Ticket Readiness

Required channels:

```text
approved_service_catalog
contractual_sla_definitions
service_availability_observations
incident_records
problem_records
change_records
customer_tickets
response_and_recovery_timestamps
responsible_team_and_escalation
asset_lifecycle_records
root_cause_and_corrective_actions
customer_satisfaction
maintenance_costs
external_service_benchmarks
```

All channels remain `unavailable` with `value=null` until authoritative customer sources are registered.

### SLA Contract

A production SLA definition requires:

```text
sla_id
service_id
customer_scope
measurement_window
timezone
availability_target
response_target
recovery_target
priority_rules
exclusions
approved_version
effective_from
effective_to
source_system
```

### Incident/Ticket Contract

```text
record_id
record_type
service_id
priority
opened_at
acknowledged_at
resolved_at
closed_at
status
customer_scope
responsible_team
escalation_level
root_cause
corrective_action
source_system
source_record_id
```

Missing timestamps or scope prevent metric calculation.

## 4. Internal SLA Boundary

Internal workflow fields such as `sla_violated` are platform workflow signals only. They cannot be promoted to customer contractual SLA violations without an approved service/SLA relationship, measurement window, exclusions and customer scope.

Mandatory flags:

```text
internal_threshold_not_customer_contract_sla=true
platform_metrics_not_customer_service_quality=true
alert_not_confirmed_incident=true
workflow_failure_not_asset_failure=true
missing_ticket_data_not_zero_incidents=true
observability_not_root_cause=true
source_code_capability_not_observed_operation=true
```

## 5. Operations UWM Gate

Future operations-world-model contract:

```text
service_state
incident_event
maintenance_action
service_dependency_graph
failure_propagation
recovery_transition
recurrence_state
counterfactual_maintenance
held_out_incident_recovery_evaluation
```

Initial mechanism states:

```text
failure_propagation=closed
recovery_time_prediction=closed
recurrence_risk=closed
maintenance_effect=closed
sla_breach_prediction=closed
resource_dispatch_optimization=closed
```

No mechanism opens merely because logs or metrics exist.

## 6. Forbidden Metrics and Claims

```text
customer_sla_compliance_rate
service_availability_rate
mttr
mtbf
customer_satisfaction_score
ticket_closure_rate
root_cause_distribution
maintenance_cost
failure_recurrence_probability
operations_performance_rank
sla_breach_prediction
```

Unavailable values remain null.

## 7. Product Contract

Schema:

```text
uwm.operations_service_quality_readiness.v1
```

Immutable bundle:

```text
overview.json
platform_operations.json
customer_channels.json
data_contracts.json
uwm_gate.json
map.json
```

The initial map contains no customer incident geography.

## 8. API and UI

Authenticated endpoints:

```text
/api/uwm/operations-quality/overview
/api/uwm/operations-quality/platform-operations
/api/uwm/operations-quality/customer-channels
/api/uwm/operations-quality/data-contracts
/api/uwm/operations-quality/uwm-gate
/api/uwm/operations-quality/map
```

Independent tab: `运维与服务质量`.

The UI displays platform operation capabilities, source evidence, customer SLA/ticket readiness, missing contracts, closed UWM mechanisms and explicit interpretation warnings.

## 9. Verification

Independent verification rejects:

- bundle mismatch;
- platform capability without evidence path;
- internal threshold promoted to contractual SLA;
- non-null unavailable customer values;
- calculated MTTR, MTBF, availability or compliance without authoritative records;
- open UWM mechanisms without incident/recovery calibration;
- inferred root cause or customer satisfaction;
- fabricated values above zero.

## 10. Maximum Claim and Ledger

Maximum claim:

```text
platform_operations_evidence_and_customer_service_management_readiness
```

Demand 18 target:

```text
implementation_status=implemented_evidence_bounded
```

This product is not a customer SLA performance report or an operations predictive model.
