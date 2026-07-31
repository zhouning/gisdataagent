# ADR-074: Chongqing real-source admission manifest

**Status**: Accepted

**Date**: 2026-07-31

## Context

AR-2 needs representative real sources before it can define ingestion, quality and lakehouse contracts. The available Chongqing planning-institute sample spans elevation, roads, remote-sensing land cover, buildings, cultural-planning data, population, POI/AOI, commuting and search activity. Earlier work profiled 16 useful assets, but that research inventory did not bind the complete source payload and had no authority to admit content.

The original ZIP and the current extracted working set are not identical. All 532 archive entries in the `01数据样例` scope are present, but only 526 match by size and CRC, 6 differ and 52 files exist only in the extracted set. The additional material includes expanded FileGDB content and generated sidecars. Without derivation provenance, treating the extracted set as a byte-exact extraction would create a false source claim.

## Decision

Adopt the checked M3-28 manifest as a path-free, content-addressed and metadata-only admission contract for the full Chongqing source set.

The manifest binds:

- the 468,462,251-byte source archive with SHA-256 `2043b60c2f4f7f32a31388a634fae4ac28534990e205aa86b8df0e4b64dcbbca`, 533 files and 694,164,379 uncompressed bytes;
- the 532-entry archive source scope with 694,147,946 bytes;
- the 584-file, 700,610,744-byte extracted working set with payload fingerprint `e7e81e4f53f9f174792f500fbfdfde6bee30ec03beac8cbd91771fe09f548ea6`;
- 11 complete physical source groups and 16 metadata asset profiles;
- the earlier 16-row research inventory as `research_inventory_only`, never as admission authority.

The checked evidence contains aggregate physical inventories, schema field names, counts, CRS, bounds, roles and content fingerprints. It contains no absolute source path, source file, geometry, row value, credential or record-level payload.

The validator freezes the archive/extracted comparison at 526 exact matches, 6 modified entries, no missing archive entry and 52 extracted-only files. It therefore requires `archive_integrity_verified=true` but `archive_extracted_entry_multiset_verified=false`, and retains `source_binding:extraction_derivation_provenance_missing` as an admission blocker.

Every source group also remains blocked on owner, license, retention and access decisions, plus domain-specific privacy, commercial terms, attribution, vintage, lineage or sensitivity review where applicable. The manifest reports 57 unique blockers.

## Authority boundary

Metadata profiling is allowed; content admission is not. The manifest does not create a `ResourceVersion`, `PolicyDecision`, `Approval`, `PlatformRun`, scheduler command, provider mutation, landing object, lakehouse table or data product.

The local ZIP remains the observed archive payload and the extracted directory remains a working set. Neither local path is a production source authority. The checked JSON is evidence about those bytes, not a copy of them and not authority for owner, license, retention, access, privacy or publication decisions.

CI validates only the checked evidence and never requires the local source paths. Any future admission must resolve every blocker, preserve derivation provenance and execute a fresh protected ingestion. M3-24/M3-25 retained material cannot be promoted as a substitute.

## Consequences

**Positive**: AR-2 now has a reproducible real-source baseline covering the full available Chongqing corpus instead of a synthetic fixture or one 20-feature slice.

**Positive**: archive integrity, extracted working-set identity and asset metadata are independently bound, so later ingestion can detect source drift without committing restricted data.

**Positive**: the earlier village-planning scope is corrected to 28 Shapefile layers, 20 non-empty layers and 8,050 features; the prior count of 31 described all Shapefiles under the root, not the village subset.

**Negative**: M3-28 intentionally admits no content and leaves 57 blockers unresolved. AR-2 is `in_progress`, not verified.

**Negative**: the extracted working set cannot become an admitted landing source until its six modified and 52 additional files have documented derivation provenance.

## Verification

```bash
./scripts/chongqing-real-source-admission.sh validate
python -m pytest data_agent/test_chongqing_real_source_admission.py -q
```

The checked evidence fingerprint is `a2196495d845d61be939c7fc36a7f05c3567e365599d2d04be0aab9c568459c1`; its file SHA-256 is `9b5c20369c235f7e0a2f2cb0a21cee77f86981aa273bac196605a4803b05ce83`.
