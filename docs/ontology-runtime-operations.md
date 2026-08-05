# Natural-resource ontology runtime operations

This runbook implements [ADR-139](architecture-decisions/adr-139-natural-resource-ontology-runtime.md).
PostgreSQL `gda_ontology` is the runtime authority, immutable packages are the
release and recovery unit, and Fuseki/TDB2 is a rebuildable RDF read projection.

## Security roles

- The EA source account must have `CONNECT`, `USAGE`, and `SELECT` only. The
  compiler starts an explicit PostgreSQL read-only transaction.
- Runtime application roles receive `SELECT` on `gda_ontology` only.
- Release automation uses a dedicated login that is a member of the existing
  `gda_ontology_publisher` role. Configure the migration setting
  `gda.ontology_publisher_role` when a different role name is required.
- `ONTOLOGY_AUTHORITY_URL`, EA credentials, and Fuseki admin credentials belong
  in the deployment secret manager. Do not inject publisher credentials into
  application pods.

## Release flow

Apply migration `117_natural_resource_ontology_authority.sql` before the first
release. Build with structured EA environment variables so reserved characters
in credentials are not hand-escaped:

```bash
export EA_REPOSITORY_HOST='<ea-host>'
export EA_REPOSITORY_PORT='5432'
export EA_REPOSITORY_DATABASE='<ea-database>'
export EA_REPOSITORY_USER='<readonly-user>'
export EA_REPOSITORY_PASSWORD='<secret-manager-value>'

python -m data_agent.ontology.cli build \
  --standard-zip '<standard-archive.zip>' \
  --legacy-docx-dir '<controlled-legacy-doc-conversions>' \
  --output-root data_agent/ontology/packages/natural_resource_one_map \
  --semantic-version '<semver>' \
  --activate
```

The build fails on missing standard volumes, duplicate IDs/URIs, dangling
relations, structural errors, or SHACL failure. Source quality findings remain
warnings in `validation-report.json` and require domain-governance review.

Publish only a hash-verified, conforming package:

```bash
export ONTOLOGY_AUTHORITY_URL='<publisher-postgresql-dsn>'
python -m data_agent.ontology.cli publish \
  --package-dir 'data_agent/ontology/packages/natural_resource_one_map/<semver>' \
  --actor '<release-identity>'
```

Publication is one transaction. Content is inserted as draft, validation and
package evidence are recorded, the version becomes published, and the active
pointer changes last. Published content tables reject update/delete operations.
Publishing an already published package is idempotent and can switch the active
pointer back to that version for rollback.

## RDF projection

Compose users start `ontology-rdf` and the one-shot `ontology-projection`
verifier. Kubernetes users build the pinned image from
`docker/ontology-fuseki/Dockerfile` and apply `k8s/overlays/ontology-fuseki`.
The image verifies the official Apache Jena/Fuseki SHA-512 digests, loads the
immutable Turtle artifact into TDB2 when its package digest changes, and starts
a query/read-only Graph Store service. The versioned projection Job verifies
the expected triple count before release acceptance.

Fuseki is not an authority. A projection failure must not change the active
PostgreSQL version. The semantic gateway continues through PostgreSQL, or falls
back to the installed package when PostgreSQL is unavailable.

## Runtime checks

- `/api/ontology/status`: active version/hash, authority backend, fallback hash
  match, validation state, and RDF projection state.
- `/api/ontology/validation`: structural and SHACL evidence plus source-quality
  observations.
- Alert when PostgreSQL authority falls back to the package, active/fallback
  hashes differ, validation does not conform, or a Fuseki projection checkpoint
  is failed/stale.
- Keep API budgets at or below 200 search rows, 500 fields/relations/nodes, and
  graph depth 3. Raw unbounded SPARQL is not exposed to browsers or Agent tools.

## Source updates

Never overwrite a package directory or reuse a semantic version for changed
artifacts. Recompile from the EA snapshot and all standard volumes, review new
mapping conflicts and quality warnings, publish the next version, then rebuild
the RDF projection. Bulk geometries remain in PostGIS, GeoParquet/COG, ArcPy,
or object storage and are not copied into RDF.
