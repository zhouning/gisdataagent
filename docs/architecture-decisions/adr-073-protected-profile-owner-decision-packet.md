# ADR-073: Protected profile owner decision packet

**Status**: Accepted

**Date**: 2026-07-31

## Context

ADR-072/M3-26 binds the checked Chongqing 20-feature predecessor to the production identity and object-store readiness gates. Its deterministic decision is valid but closed: 40 identity profile fields, 43 object-store profile fields, one identity attestation and one object-store attestation remain unresolved.

Those 85 blockers are machine-readable, but a flat list does not identify who must decide each concern, what it depends on, which profile paths may change, or which protected artifacts must prove the result. Selecting an IdP, provider account, bucket, region, KMS key or production owner inside the repository would exceed repository authority and create false production claims.

## Decision

Adopt the checked M3-27 protected profile owner decision packet as the only repository-maintained decomposition of the M3-26 blocker inventory.

The packet binds the M3-26 evidence file SHA `62624b96d83b085cbb82d29d618042d7f4faa5193847c26af859ec1c87cd4f11`, decision SHA `39246eacdd1793f23aecb71195cc4c9d8c63d7125aad8cd9bbb59a96c588cd73` and contract SHA `39411248b37b7d8d43ac7ad37737de15d6b6d4c5e4feb2088f0a87cec888b5f9`.

It assigns every blocker exactly once across 16 dependency-ordered groups:

1. identity federation: 7;
2. OpenMetadata identity binding: 6;
3. Gravitino identity binding: 6;
4. metadata TLS: 4;
5. persistent catalog: 5;
6. metadata tenancy: 2;
7. identity operations and runbooks: 10;
8. object-store provider: 9;
9. object-store workload identity: 5;
10. object-store transport: 5;
11. object-store encryption and KMS: 3;
12. object-store durability and consistency: 5;
13. object-store tenancy: 1;
14. object-store operations, SLOs and runbooks: 15;
15. protected identity attestation: 1;
16. protected object-store attestation: 1.

Each group contains stable owner roles, dependencies, exact M3-26 blockers, writable profile paths, allowed and forbidden decision boundaries, required artifacts, a protected verification command and `status=unresolved`.

The validator fails closed when:

- the M3-26 predecessor file or bound SHA changes;
- any blocker is missing, duplicated, invented or assigned more than once;
- a dependency is unknown or the graph contains a cycle;
- any group is marked resolved or its checked content drifts;
- a credential-bearing field appears;
- any execution, ingestion or production claim becomes true.

## Authority boundary

The packet does not record approved production choices. Owners must approve and materialize decisions in:

- `config/metadata-fabric-identity.production.yaml`;
- `config/metadata-fabric-object-store.production.yaml`.

The two final blockers can only be removed by fresh outputs from their protected environments. Both attestations must bind the approved profiles and the same source revision. Passing their individual gates still requires a new M3-26 composite evaluation.

The packet never creates a PolicyDecision, Approval, PlatformRun, scheduler command, provider mutation or production data product. It cannot promote retained M3-24/M3-25 material and it does not authorize a fresh ingestion.

## Consequences

**Positive**: every external dependency is assignable, reviewable and testable without inventing production infrastructure choices.

**Positive**: exact blocker coverage and the dependency graph are enforced in CI, so owner work cannot silently diverge from the admission gate.

**Negative**: M3-27 intentionally leaves all 16 groups unresolved and does not reduce the current count of 85 blockers.

**Negative**: production progress now requires decisions and protected evidence from IAM, metadata, lakehouse, cloud, storage, network, security, governance and SRE owners outside repository code.

## Verification

```bash
./scripts/metadata-fabric-protected-profile-decision-packet.sh validate
python -m pytest data_agent/test_metadata_fabric_protected_profile_decision_packet.py -q
```

The checked packet SHA is `b23e1becafa0c91541a653d467e7959107008d4dc41576018b57b564e6b46a36`.
