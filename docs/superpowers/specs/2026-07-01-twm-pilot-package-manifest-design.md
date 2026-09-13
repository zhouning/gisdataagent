# TWM P2A Pilot Package Manifest Design

## Goal

Add a narrow `territory_world_model.pilot_package.v1` report that makes one pilot
package the canonical training and evaluation unit before P2B model shootouts.
The package must bind state contract evidence, dynamics dataset MREP trace,
same-case baseline evidence, split definitions, the dynamics evaluation bundle
and an optional Lance sidecar contract into one auditable report.

## Scope

This slice does not add a new neural model, train a new candidate, change
existing readiness/evaluation semantics or promote any production claim. It only
adds a packaging contract and route/tool exposure so later MLP, graph,
transformer and robustness comparisons reference the same data snapshot and
baseline versions.

## Architecture

The service adds `pilot_package_report(state_version_id, payload)` next to the
existing TWM dynamics reports. It reuses existing report producers instead of
duplicating their logic:

- `state_contract_report` for hierarchy, evidence and claim-ladder context;
- `dynamics_training_examples` for the canonical dynamics dataset and MREP
  trace;
- `dynamics_evaluation_bundle` for readiness, evaluation and registry evidence;
- payload-provided `production_onboarding_report`,
  `baseline_export_validation_report` or `baseline_evidence_pipeline_report`
  when available.

The report returns:

- `schema`: `territory_world_model.pilot_package.v1`;
- `status`: `pass` only when state contract, MREP trace, dynamics bundle,
  production gate and same-case baseline gate pass; otherwise `review` or
  `blocked`;
- `trajectory_dataset_manifest`: a
  `territory_world_model.trajectory_dataset_manifest.v1` summary derived from
  the dynamics dataset examples;
- `split_summary`: temporal/spatial split references from the dataset MREP trace
  and payload;
- `evidence_summary`: dataset hash, package ID, versions, gate statuses and
  baseline references;
- `promotion_blockers`: missing evidence that prevents using the package for
  promoted model comparisons;
- optional `lance_sidecar_manifest` only when `include_lance_sidecar` is true.

## Data Flow

1. Caller posts a state ID and optional payload.
2. The service loads the state and state bundle, then builds or accepts the
   dynamics dataset.
3. The service builds the state contract and dynamics evaluation bundle.
4. The service derives a trajectory manifest from dataset examples:
   `state_t_ref`, `state_t_plus_1_ref`, `action_ref`, target heads, split
   counts, source lineage and dataset hash.
5. The service evaluates package gates:
   - state contract present;
   - MREP trace present with dataset snapshot hash;
   - dynamics evaluation bundle present;
   - production observed-history gate passed when supplied;
   - same-case baseline validation passed when supplied or required.
6. The API and ADK toolset expose the same report without adding extra behavior.

## Error Handling

Missing state IDs raise `LookupError`, following existing TWM report methods.
Malformed non-object JSON route payloads return HTTP 400. Missing optional
production or baseline evidence does not crash the report; it becomes a
machine-readable blocker in `promotion_blockers`.

## Testing

Tests must be written first and verify:

- service report links state contract, MREP trace, dynamics bundle and trajectory
  manifest;
- same-case baseline evidence is required when `require_same_case_baseline` is
  true;
- Lance sidecar is optional and explicitly marked as derived sidecar storage, not
  authoritative storage;
- API route and ADK tool registry expose the pilot package report.

## Claim Boundary

The pilot package report is a reproducibility and audit contract. It does not
prove model superiority, production readiness, future parcel geometry generation
or autonomous planning. Those claims remain gated by later P2B/P2C/P3 evidence.
