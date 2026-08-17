# ADR-080: Chongqing protected admission verifier workflow

**Status**: Accepted

**Date**: 2026-08-17

**Decision owners**: Platform Architecture, Data Platform, Data Governance, Security

## Context

M3-32 defines a deterministic intake/evaluate/verify contract for the fifteen
external inputs required by the Chongqing admission readiness record. Running
that evaluator from a developer shell, however, cannot establish protected
verifier identity, environment approval or artifact provenance. The workflow
boundary must be explicit before real attestations can be consumed.

The boundary must not gain source-payload access, provider credentials,
scheduler permissions or ingestion authority. A successful evidence evaluation
is still only eligibility for a separate admission decision.

## Options considered

| Option | Benefit | Limitation | Decision |
|---|---|---|---|
| Evaluate from a developer workstation | Minimal setup | No protected identity, approval or artifact provenance | Rejected |
| Commit an attestation bundle to the repository | Easy CI integration | Makes mutable repository content look authoritative and may expose evidence metadata | Rejected |
| Protected environment workflow consuming a metadata-only secret bundle | Environment approval, exact verifier revision and GitHub provenance; no source access | Requires dedicated runner/environment provisioning and secret rotation | Adopted |

## Decision

Adopt `.github/workflows/verify-chongqing-admission.yml` as the M3-33 protected
verifier workflow contract.

The workflow:

1. can run only by manual dispatch from `main` in the protected
   `chongqing-admission` environment;
2. uses a dedicated `[self-hosted, linux, gda-admission]` runner and checks out
   the exact `github.sha` without persisted credentials;
3. accepts only a base64-encoded metadata attestation JSON from the protected
   environment secret, writes it with a restrictive umask, and never reads the
   Chongqing source payload;
4. binds evaluation to the exact M3-31 logical and file fingerprints;
5. runs the M3-32 evaluator and integrity verifier, requiring
   `attestation_valid=true` and `admission_eligible=true` while asserting every
   content, Landing, ResourceVersion, PlatformRun, scheduler, provider and
   production authority claim remains false; and
6. uses GitHub OIDC provenance to attest the metadata-only input bundle and
   report, then uploads them as a bounded-retention artifact.

The secret is an input transport, not an authority by itself. Environment
reviewers, branch restrictions, runner ownership and secret rotation must be
provisioned before the workflow can produce accepted protected evidence.

## Authority boundary

M3-33 contains no connector, source scan, payload copy, Landing creation,
ResourceVersion mutation, PlatformRun creation, scheduler submission or
provider client. The workflow cannot authorize ingestion or production. A
successful report must be consumed by a separate admission decision and
immutable Landing authority workflow that does not yet exist.

The checked-in workflow and synthetic/static tests prove only the workflow
contract. They do not prove that the protected environment, runner, reviewer
policy, external attestations or production identities exist.

## Consequences

**Positive**: real external evidence now has one auditable execution path bound
to an exact verifier revision and provenance artifact.

**Positive**: environment configuration or evidence gaps fail before any
authority-bearing action is possible.

**Negative**: AR-2 remains `in_progress`; the dedicated environment and runner
must be provisioned and all fifteen real attestations supplied before the first
protected run.

## Verification

```bash
python -m pytest data_agent/test_chongqing_protected_admission_workflow.py -q
```
