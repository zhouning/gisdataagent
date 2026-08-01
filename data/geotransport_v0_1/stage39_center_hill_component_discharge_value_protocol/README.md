# Stage 39 Center Hill Component-Discharge Value Protocol

Stage 39 freezes a source-only value protocol and exact request plan for the
four component-discharge identities admitted by Stage 38. It performs no
network request and acquires no values.

## Frozen evidence

The protocol binds:

- Stage 34 temporal-semantics ledger and `34/34` gates;
- Stage 38 component-catalog ledger and `34/34` gates.

An hourly CWMS composite is treated as an interval average over `[-60m, 0m]`
at its end label. The observation remains a component boundary flux, not a
gate command, human action, or causal intervention.

## Planned support

The four series are Orifice, Sluice, Spillway, and Turbine Flow. Each is split
into five annual requests covering `2021-01-01T00:00:00Z` through
`2026-01-01T00:00:00Z`, for 20 logical requests total.

The expected grid contains 43,825 unique inclusive hourly positions per
component. Annual windows share boundary timestamps; duplicates must be
identical before one copy is retained. Explicit nulls and quality codes are
preserved without fill or approval interpretation.

Synchronized total discharge is not yet admitted. A future audit may mark an
hour eligible only when all four component values are real at that timestamp.
Partial sums, missing-component imputation, and negative component values are
rejected.

## Request boundary

- allowed host: `cwms-data.usace.army.mil`;
- exact logical requests: 20;
- maximum attempts: three per request, 60 total;
- maximum response: `1MB` per attempt;
- maximum persisted responses: `20MB`;
- retry worst-case response bytes: `60MB`;
- page size: 20,000; unexpected pagination fails closed;
- workspace, tailwater, tributary, and downstream data requests: none.

The planner has no network execution path. Fresh approval is required before
the requests can be executed.

## Artifacts

- `protocol.json` SHA-256:
  `b065308dd8b5e44aebd08d3da41dc6a0d822cf4aeb5c5ea5e88500ad95aa557b`;
- `value_acquisition_plan.json` SHA-256:
  `0870a5c636d59b8074efaab199b881e4a384b58d19fd7410ca12e00a329e4f26`;
- `stage39_component_discharge_value_plan_gates.json` SHA-256:
  `6b205a953f4f69f27322366fdbdf86cb7241e03529d13e4fa61fcdab5a179802`.

All 19 focused tests and all 34 gates pass with status
`stage39_component_discharge_value_plan_frozen_values_pending_approval`. The
rationale is in ADR-080.

## Subsequent approved execution

The frozen plan was later approved and executed as the input to Stage 40. All
20 requests succeeded on the first attempt and persisted `4,225,697` bytes.
The acquisition manifest SHA-256 is
`ed77dacf3743713817177ba6fd7e553c71823693d831af5d38523dbb5fb45a0b`.
Scientific support and remaining refusal boundaries are reported by Stage 40;
the Stage 39 protocol and plan hashes remain unchanged.
