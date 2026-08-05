---
type: Attested Computation
title: Banzhu land-structure change analysis
description: Version-locked replay that links structure deltas to changed parcels and ontology states.
tags: [banzhu, land-structure, semantic-analysis]
status: stable
runtime: python
parameters:
  - { name: scenario_id, type: string, required: true }
computation: /references/computations/version-locked-ontology-demo.json
executor:
  resource: /references/executors/ontology-demo-executor.md
  receipt: [receipt_id, concept_id, parameters, executed_computation, input_artifacts, result, result_sha256]
attester:
  resource: /references/attesters/scenario_receipt_attester.py
generated: { by: gda-ontology-okf-producer/1.0, at: 2026-08-05T00:00:00Z }
verified: { by: process:gda-ontology-release-gate, at: 2026-08-05T00:00:00Z }
sources:
  - id: ontology-package
    resource: /sources/ontology-package.md
    title: Natural-resource ontology immutable package V2.0.1
  - id: demo-bundle
    resource: /sources/customer-demo-bundle.md
    title: Customer demo data bundle
---

# Computation

The executor binds `scenario_id=banzhu_adjustment`, replays the sanctioned
analysis, and returns a receipt. The deterministic attester independently checks
the computation resource, input artifact hashes, parcel counts, areas, process
counts, and selected structure deltas before results can be displayed.
