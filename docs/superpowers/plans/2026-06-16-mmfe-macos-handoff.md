# MMFE macOS Handoff

Date: 2026-06-16

## Branch

- Repository: `https://github.com/zhouning/gisdataagent.git`
- Branch: `feat/v12-extensible-platform`
- Latest pushed MMFE commit before this handoff: `2b68e85 feat: expose MMFE publish plan tool`

On macOS:

```bash
git clone https://github.com/zhouning/gisdataagent.git
cd gisdataagent
git checkout feat/v12-extensible-platform
git pull origin feat/v12-extensible-platform
```

## Current MMFE State

MMFE is now defined and implemented as a universal multimodal semantic fusion
engine with geospatial-specialized adapters. Geospatial data is a critical
modality family, but not the boundary of MMFE.

Completed contract and orchestration layers:

- Semantic fusion product manifest with schema, product id, field contracts,
  semantic mappings, alignment scoring, review items, lineage, quality, and
  AI-ready chunks.
- Generic modality metadata on source profiles: `modality`, `media_type`, and
  `adapter_family`.
- Lightweight generic profiling for text/Markdown, GraphML, AI/model-output
  sidecars, documents/images/audio/video/unknown binaries as future adapter
  entry points.
- Raster semantic evidence: sidecar/STAC/ISO XML metadata, band scale/offset,
  nodata/unit, CRS/grid semantics, feature-chip summaries.
- Point-cloud semantic evidence: LAS/LAZ metadata, classification/intensity/RGB
  and return evidence, LAZ backend evidence, chunking plan.
- PDAL pipeline and runner contracts.
- External AI sidecar and runner contracts.
- Vector publish contracts for pgvector and LanceDB.
- Iceberg analytical lakehouse publish contract.
- Sedona-on-Iceberg runner contract.
- STAC discovery catalog publish contract.
- `publish_semantic_product()` orchestration across Iceberg, STAC, pgvector,
  and LanceDB contracts.
- `plan_semantic_product_publish()` ADK FusionToolset tool for dry-run publish
  preflight from an agent workflow.

Important boundary: most of the above is a stable dependency-free contract,
validation, orchestration, and test layer. It is not yet the production backend
adapter layer that imports and runs LanceDB, Spark/Iceberg/Sedona, PDAL, or
third-party AI model runtimes directly.

## Verification Already Run on Windows

```powershell
.\.venv\Scripts\python.exe -m pytest `
  data_agent\test_fusion_toolset_publish_plan.py `
  data_agent\test_fusion_engine.py `
  data_agent\test_fusion_semantic_alignment.py `
  data_agent\test_fusion_semantic_product.py `
  data_agent\test_fusion_semantic_publisher.py `
  data_agent\test_fusion_lakehouse_publisher.py `
  data_agent\test_fusion_v2_semantic.py `
  data_agent\test_fusion_v2_integration.py `
  data_agent\test_fusion_v2_explainability.py `
  data_agent\test_fusion_v2_conflict.py `
  data_agent\test_fusion_ai_semantics.py `
  data_agent\test_fusion_pdal_pipeline.py `
  data_agent\test_toolsets.py -q
```

Result:

```text
369 passed, 21 warnings
```

## Recommended macOS Next Slice

Stop extending pure contracts for now. Use the macOS environment to implement
real backend adapters in this order:

1. Local LanceDB real adapter
   - Install/import `lancedb` only in the adapter path or optional dependency
     path, not in MMFE core import time.
   - Read a `.semantic.json` manifest.
   - Use the existing vector publish spec.
   - Generate embeddings through an injected adapter first; a deterministic
     test embedder is enough for the first slice.
   - Actually create/open a local LanceDB dataset/table and insert rows.
   - Query the table back in an integration test.

2. pgvector real adapter
   - Use the existing PostgreSQL/PostGIS configuration path if available.
   - Create table with metadata JSONB and vector column.
   - Upsert vector records from the existing semantic vector publish spec.
   - Add a retrieval smoke test.

3. Iceberg/Sedona production adapter examples
   - Keep Spark/Iceberg/Sedona optional.
   - Add executable example scripts and config templates for S3-backed Iceberg.
   - Add docs for catalog, warehouse URI, Spark config, Sedona SQL, and expected
     manifest patch behavior.

4. PDAL/LAZ real execution path
   - Keep PDAL optional.
   - Add a real executor wrapper and deployment notes for conda/brew/container
     installs.
   - Use the existing runner spec and chunk artifact manifest contracts.

## Files Most Relevant for Continuation

- `data_agent/fusion/semantic_product.py`
- `data_agent/fusion/semantic_publisher.py`
- `data_agent/fusion/lakehouse_publisher.py`
- `data_agent/fusion/pdal_pipeline.py`
- `data_agent/fusion/ai_semantics.py`
- `data_agent/toolsets/fusion_tools.py`
- `data_agent/test_fusion_semantic_publisher.py`
- `data_agent/test_fusion_lakehouse_publisher.py`
- `data_agent/test_fusion_toolset_publish_plan.py`
- `docs/superpowers/specs/2026-06-15-mmfe-semantic-fusion-product-design.md`
- `docs/superpowers/plans/2026-06-15-mmfe-semantic-fusion-product.md`

## Windows Workspace Note

The Windows workspace still has unrelated local dirty changes in NL2SQL,
temporary output, and benchmark files. They were intentionally not staged or
committed with MMFE. A fresh macOS clone of `feat/v12-extensible-platform` will
not include those local dirty files.
