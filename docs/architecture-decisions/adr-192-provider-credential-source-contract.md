# ADR-192: Provider credential source contract

## Status

Accepted

## Context

The OpenMetadata lineage worker, master-data worker, provider-read bridge and
provider-search bridge all need the same bearer-token credential. Runtime
containers receive a mounted secret through an absolute `*_BEARER_TOKEN_FILE`,
while Compose configuration exposes the host-side `*_BEARER_TOKEN_SOURCE` used
to construct that mount. Previously, only the file variable was understood by
the Python processes, and each module performed its own path validation.

That split made direct host execution and Compose interpolation disagree about
which credential was configured. It also allowed future callers to implement
different relative-path, duplicate-source or non-file behavior.

## Decision

1. Centralize provider bearer-token path resolution in
   `data_agent.provider_credentials`.
2. `*_BEARER_TOKEN_FILE` is the direct runtime mount contract and must be an
   absolute path. `*_BEARER_TOKEN_SOURCE` may be absolute or relative to the
   process working directory, which is the documented direct-process meaning
   of a Compose-style source path.
3. If both variables are set, both paths must resolve to the same canonical
   regular file. A mismatch, missing path, directory, special file or unsafe
   relative `*_FILE` fails closed before a provider client is created.
4. The resolver validates metadata only; token bytes are read only at request
   time by the existing provider client and are never included in configuration
   summaries, errors or evidence.
5. `FILE` remains the preferred operational input. `SOURCE` is a compatibility
   and bootstrap input, not an identity mechanism, OIDC implementation or
   workload-identity proof. Credential rotation takes effect on the next
   request after the mounted file is replaced; no token content is persisted in
   the GDA ledger.

## Evidence

- `data_agent/provider_credentials.py` contains the shared resolver and regular
  file validation.
- OpenMetadata lineage/master-data workers and provider read/search bridges use
  the resolver for `GDA_OPENMETADATA_BEARER_TOKEN_FILE` and
  `GDA_OPENMETADATA_BEARER_TOKEN_SOURCE`.
- `data_agent/test_provider_credentials.py` covers source-only, file-only,
  relative/absolute paths, equivalent dual configuration, conflicting paths,
  missing paths, non-files and all four integration call sites.
- Focused provider/worker regression: `44 passed`; Ruff and Python compile pass.
- The fixed OpenMetadata `1.13.1` acceptance topology ran the bounded
  provider-search and UUID read-after-search through `SOURCE` only; the report
  is `.tmp/metadata-fabric/openmetadata-provider-search-acceptance-report.json`
  (`0600`, SHA-256
  `af678ea2f2c832057a8fb18908edf76875a7b5425119e3dbb35e26eb7787f759`).

## Consequences

Direct host execution can use the same source path contract that Compose uses
to select the mounted secret, while runtime containers continue to consume
only the mounted absolute file. Duplicate configuration becomes deterministic
and fail-closed, and token path validation no longer drifts between modules.

This ADR does not establish OIDC, workload identity, secret-manager rotation,
provider HA, backup/restore, cross-tenant isolation or a production OpenMetadata
foundation. Those remain AR-1 exit gates.

## Revisit triggers

- A deployment platform provides a stronger secret-reference API than a local
  source path and mounted file.
- OIDC/workload identity replaces bearer-token files for a provider profile.
- A provider requires multiple credential files or a token format beyond one
  non-empty whitespace-free bearer token.
