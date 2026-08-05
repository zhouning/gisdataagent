# AR-2 Geospatial Lakehouse Runtime Handoff

**Saved at**: 2026-08-02
**Continuation branch**: `feat/ar2-geospatial-lakehouse-runtime`
**Base branch**: `origin/feat/ar2-chongqing-real-source-admission`
**Roadmap state**: AR-2 `in_progress`

## Resume Objective

Continue making GIS Data Agent a next-generation data platform. The next bounded milestone is
snapshot-bound position/MOR destructive-write conflict isolation. Do not broaden the claim to
production readiness, automatic retry, HA, Kubernetes, REST/Gravitino interoperability, or
cross-system exactly-once.

## Verified Through ADR-120

- ADR-101 through ADR-106 establish declarative source adapters, governed connectors,
  ApprovalCase authority, SourceSync checkpoint authority, Flink event ingestion, and PostgreSQL
  CDC certification.
- ADR-107 through ADR-109 establish Spark/Flink/MinIO Iceberg interoperability, checkpoint
  recovery, cancellation, and uncertain-commit reconciliation.
- ADR-110 through ADR-115 establish concurrent append and snapshot-bound overwrite,
  copy-on-write delete, partition update/delete conflict isolation, and the single-operation Flink
  writer lifecycle.
- ADR-116 through ADR-120 establish bidirectional position/equality delete interoperability,
  update-versus-equality-delete conflict isolation, equality-delete authorization versus insert
  isolation, and a Flink TaskManager position-delete writer.

Latest real acceptance:

- Report: `.tmp/source-sync-certification/chongqing-osm-flink-spark-position-delete-interop-report.json`
- Report SHA-256: `ec13afd09a3d8617519c112461009495da8265131cc3b53beb43489549fd95d5`
- Top-level gates: `12/12`
- Snapshot chain: `3121089764148917328 -> 1910388505160970892`
- Physical binding: `road_id=102262020`, original data-file position `1`
- Physical delete Parquet SHA-256:
  `e1a6ba9f30d2dbe34ad546bf6fa995ee99529830c6986aa7cf965ebe44a53746`
- Cleanup: 8 MinIO objects removed; isolated Flink/JDBC Catalog containers and work directory
  removed; main SourceSync remained `0/0/0`.
- Related regression: `58 passed`.

ADR-119 acceptance immediately preceding it:

- Report: `.tmp/source-sync-certification/chongqing-osm-spark-flink-equality-delete-insert-conflict-report.json`
- Report SHA-256: `af051adf8d4e54c467b29d42db0b33f7d1c0bd21c965c303d606a8a26398bafe`
- Top-level gates: `16/16`.

## Real Data Contract

- Source:
  `data_agent/uploads/data_products/chongqing-osm-roads/v1.2.0/silver/chongqing-osm-roads-standardized.geoparquet`
- Source rows: `50,366`
- Source SHA-256: `8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`
- Source product SHA-256:
  `c0e99b5f69239e9ade8360399edc15fa47e71f9cfb68939223d3b8f4c3041164`
- Spark: 3.5 / Iceberg 1.6.1.
- Flink: 1.19.3 / Iceberg 1.7.2.
- Runtime: short-lived local Docker containers, not Compose services and not Kubernetes.

The source file is intentionally under the ignored uploads tree and is not pushed to GitHub. Real
acceptance requires the existing local source and local frozen connector artifacts.

## Non-negotiable Constraints

- ADRs are append-only historical records. Add ADR-121 for the next decision; do not rewrite
  ADR-112 through ADR-120.
- Do not modify migration `104` while implementing the next destructive-write milestone.
- Keep `classloader.check-leaked-classloader=true` and observe it through JobManager REST.
- Keep one provider operation per Flink writer job.
- Keep control-plane authorization, provider commit, and fresh-state retry authorization separate.
- Do not weaken evidence gates to accommodate provider behavior.
- Preserve unrelated dirty files in the primary worktree.

## First Commands Next Session

```bash
git fetch origin
git switch feat/ar2-geospatial-lakehouse-runtime
git status --short
git log -1 --oneline --decorate
sed -n '1,240p' docs/handoffs/2026-08-02-ar2-geospatial-lakehouse-runtime.md
```

Before starting ADR-121, re-run the focused contracts:

```bash
uv run --offline pytest -q \
  data_agent/test_chongqing_osm_flink_spark_position_delete_interop.py \
  data_agent/test_chongqing_osm_spark_flink_position_delete_interop.py \
  data_agent/test_chongqing_osm_spark_flink_equality_delete_insert_conflict.py \
  data_agent/test_chongqing_osm_spark_flink_equality_delete_conflict.py
```

## Next Milestone Boundary

Build a deterministic race in which an intent is bound to the baseline snapshot and a competing
position/MOR commit advances the JDBC Catalog. Require provider-level conflict rejection, catalog
pointer preservation, independent fresh-state reconciliation, Spark time travel, physical delete
file evidence, complete cleanup, and unchanged SourceSync. Choose one narrow same-file/same-key
case first; leave partitioned/multi-file, automatic retry, checkpoint writers, HA, and K8s open.
