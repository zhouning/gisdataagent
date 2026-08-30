---
type: Attested Computation
title: Heping land-conversion auxiliary precheck
description: Version-locked replay that classifies changed parcels, evidence gaps, and registered spatial constraints.
tags: [heping, land-conversion, auxiliary-precheck]
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
    title: Natural-resource ontology immutable package V2.1.0
  - id: demo-bundle
    resource: /sources/customer-demo-bundle.md
    title: Customer demo data bundle
---

# Computation

The executor follows the sanctioned JSON computation resource. The agent may
only bind `scenario_id=heping_review`. The deterministic attester re-reads the
version-locked inputs, recomputes authoritative counts, and refuses display if
the receipt, computation digest, input hashes, or displayed result differs.

# Scope

Attestation proves replay integrity and result consistency. The output remains
an auxiliary precheck and is not statutory approval.
