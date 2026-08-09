# Windows native-lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Produce a complete Windows native-lite offline deployment ZIP for the GIS Data Agent, with a deterministic native middleware profile and a silent NSIS PostGIS installation.

**Architecture:** `native-lite` is the primary name for the single-host enhanced stack: PostgreSQL 16 + PostGIS/pgvector, MinIO, JRE/Jena/Fuseki, and the local GIS/Paper9 runtime. Qwen chat and 768-dimensional text embeddings are external intranet dependencies served through LM Studio's OpenAI-compatible API; Ollama and local model weights are excluded. The old `production` profile remains an input alias so existing commands do not break. Distributed platform services remain explicitly out of scope.

**Tech Stack:** Python 3.11 bundle builder, JSON manifest, PowerShell 5.1 installer, pytest regression tests, SHA-256 artifact verification.

---

### Task 1: Lock the native-lite contract with regression tests

**Files:**
- Modify: `data_agent/test_windows_offline_bundle.py`

- [ ] Add assertions that `build_offline_bundle.build()` accepts `native-lite`, that the manifest declares it with the enhanced-stack required artifacts, that installer `ValidateSet` includes it, and that every former production-only installer branch also recognizes it.
- [ ] Add assertions that the default PostGIS installer argument is exactly NSIS `/S` and that `/SILENT` is absent.
- [ ] Run `python -m pytest data_agent/test_windows_offline_bundle.py -q`; expected result is failure because the current builder, manifest, and installer only know `production` and still use `/SILENT /NORESTART`.

### Task 2: Implement profile and installer behavior

**Files:**
- Modify: `deploy/windows-standalone/build_offline_bundle.py`
- Modify: `deploy/windows-standalone/bundle-manifest.json`
- Modify: `deploy/windows-standalone/install_offline_bundle.ps1`

- [ ] Add `native-lite` to builder validation and argparse choices.
- [ ] Add a manifest `native-lite` profile reusing the current production required/optional artifact IDs, with a single-host/non-distributed description; keep `production` unchanged as a compatibility alias.
- [ ] Add `$script:IsNativeStack = $Profile -in @('native-lite', 'production')` and use it for requirements, wheelhouse, PostgreSQL/PostGIS, MinIO, Fuseki/JRE, LM Studio configuration, database backend, and preflight mode.
- [ ] Exclude Ollama, Gemma4, and bundled text embedding artifacts; verify the configured LM Studio model IDs and 768-dimensional embedding response during install/startup.
- [ ] Set the default PostGIS installer arguments to `/S`, while preserving `GDA_POSTGIS_INSTALL_ARGS` as an explicit override.
- [ ] Normalize `native-lite` to the existing production verification mode where verification tools only accept `production`.

### Task 3: Make the package documentation operational

**Files:**
- Modify: `deploy/windows-standalone/README.md`
- Modify: `deploy/windows-standalone/FULL_MIDDLEWARE_INVENTORY.md` only if profile naming needs alignment

- [ ] Make `native-lite` the documented build/install command and ZIP name.
- [ ] State the single-host capability boundary and the excluded distributed services.
- [ ] Keep the documented mobile-disk handoff as ZIP plus `.sha256`, with README inside the ZIP; do not require an external `natural_resource_standard_contracts.json`.
- [ ] Ensure all paths and profile arguments in the README match the generated package layout.

### Task 4: Verify and build the deliverable

**Files:**
- Generated: `deploy/windows-standalone/out/GIS-Data-Agent-Windows-native-lite.zip`
- Generated: `deploy/windows-standalone/out/GIS-Data-Agent-Windows-native-lite.zip.sha256`

- [ ] Run the focused pytest file and the repository's Windows bundle verification scripts.
- [ ] Parse the installer with Windows PowerShell 5.1 and run builder/manifest consistency checks.
- [ ] Build the full native-lite ZIP from the available vendor payload, then verify its internal `SHA256SUMS` and external `.sha256`.
- [ ] Extract the ZIP to a temporary directory and run artifact verification against the extracted root.

### Task 5: Publish the verified branch state

- [ ] Review `git diff` and ensure generated cache directories are not staged.
- [ ] Commit the native-lite implementation, tests, plan, documentation, and verified package metadata.
- [ ] Push the commit to `origin/feat/windows-standalone-offline-bundle` and report the exact commit, ZIP size, and hashes.
