# ADR-195: DolphinScheduler Cancel Capability Admission

**Status:** Accepted (bounded control-plane slice)

## Context

The governed cancel path already requires an immutable policy decision and only
maps provider `STOP` to platform `cancelled`. Real DolphinScheduler 3.4.2
rehearsals showed that a killed shell can be projected as `SUCCESS` or `FAILURE`
instead of authoritative `STOP`. A version pin and an accepted HTTP STOP request
therefore do not prove terminal cancel conformance.

## Decision

`DolphinSchedulerProfile` now carries a version-bound cancel capability declaration:

- `unknown` is the default and is rejected before CAS state transition or the
  external STOP call.
- `certified` is production-allowed only with a non-secret evidence reference.
- `conformance_probe` is allowed only for an explicitly named sandbox/provider
  rehearsal and is reported as `probe_only`, never as production support.

The adapter emits `gda.dolphinscheduler_capability.v1`, binding API profile,
server version, cancel capability, evidence reference, admission result and a
canonical capability fingerprint. Cancellation transition evidence includes that
fingerprint. This declaration is an admission gate, not a claim that the provider
has passed terminal conformance; only a real STOP evidence report may promote a
profile from `conformance_probe` to `certified`.

## Consequences

Unknown or stale provider profiles fail closed instead of issuing a cancellation
whose terminal semantics are unknown. The sandbox rehearsal remains runnable but
is explicitly marked probe-only, preserving the distinction between testing a
provider and certifying it for production.
