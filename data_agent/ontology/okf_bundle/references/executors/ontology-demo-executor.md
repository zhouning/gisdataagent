---
type: Execution Reference
title: Version-locked ontology demo executor
description: Run instructions for sanctioned natural-resource ontology scenario replays.
resource: urn:gda:python:data_agent.ontology.okf_attestation.execute_attested_scenario
tags: [executor, deterministic, ontology]
status: stable
generated: { by: gda-ontology-okf-producer/1.0, at: 2026-08-05T00:00:00Z }
sources:
  - id: computation-spec
    resource: /references/computations/version-locked-ontology-demo.json
    title: Version-locked computation specification
---

# Execution

1. Resolve the registered OKF computation concept for `scenario_id`.
2. Load the immutable demo manifest and verify every source artifact SHA-256.
3. Execute the registered semantic classification and aggregation operations.
4. Return the declared receipt fields without relying on LLM-generated SQL or code.
5. Run the deterministic attester and display results only when it passes.
