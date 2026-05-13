# Data Standard Lifecycle Platform — P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Ingest + Analyze layers of the Standards Platform so a subject-matter expert can upload a national / industry / enterprise data-standard document (docx or XMI), have it classified, structured into clauses / terms / data-elements / value-domains, vector-indexed (pgvector 768), and deduped against previously-ingested standards — with an Outbox-backed async pipeline that survives process restarts.

**Architecture:** New in-tree subsystem at `data_agent/standards_platform/`, 16 `std_*` PG tables, raw-SQL-first (project convention), Starlette REST at `data_agent/api/standards_routes.py`, an independent outbox-worker process for async extraction + embedding + dedup, and two new React sub-tabs under a top-level `StandardsTab`. Downstream-linking tables (semantic hints / value semantics / synonyms / qc rules) get a nullable `std_derived_link_id` FK so later derive-phase work slots in cleanly.

**Tech Stack:** Python 3.13 · SQLAlchemy `text()` + psycopg2 · PostgreSQL 16 + PostGIS + ltree + pgvector 0.8.0 · Starlette · Chainlit (existing shell) · pytest + conftest fixtures · embedding_gateway.get_embeddings (768-d) · model_gateway.create_model · React 18 + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`

---

## Reading Checklist (engineer: skim before starting)

- `docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md` (the spec)
- `data_agent/api/helpers.py` — `_get_user_from_request`, `_set_user_context`, `_require_admin` (use these for every route)
- `data_agent/api/domain_standard_routes.py` — exemplar of a Starlette-Route-list module; copy this shape
- `data_agent/migration_runner.py` — how migrations are applied (file-name prefix → `agent_migrations` table)
- `data_agent/migrations/069_semantic_hints_and_value_semantics.sql` — migration DDL style
- `data_agent/db_engine.py` — `get_engine()` singleton
- `data_agent/user_context.py` — `current_user_id`, `get_user_upload_dir()`
- `data_agent/audit_logger.py` — `record_audit(username, action, status, ip_address, details)`
- `data_agent/observability.py` — Prometheus counters / histograms and `get_logger`
- `data_agent/embedding_gateway.py` — `get_embeddings(list[str]) -> list[list[float]]`, `get_active_dimension()`
- `data_agent/model_gateway.py` — `create_model(name)`
- `data_agent/standards/docx_extractor.py` — `extract(docx_path, module_name)` (will be committed in Task 1)
- `data_agent/conftest.py` — `run_async`, autouse event-loop fixture

---

## File Structure (P0 creates / modifies)

**New Python modules** (under `data_agent/standards_platform/`):

| File | Responsibility |
|---|---|
| `__init__.py` | Package marker + public export surface |
| `config.py` | Env-var parsing: allowlist, worker interval, max attempts |
| `repository.py` | Thin CRUD helpers over raw SQL for std_* tables |
| `outbox.py` | Outbox event enum + `enqueue(event_type, payload)` + claim / complete / fail primitives |
| `outbox_worker.py` | Independent entrypoint process; polls outbox, dispatches handlers |
| `ingestion/__init__.py` | Package marker |
| `ingestion/uploader.py` | Accepts docx/xmi, writes to user upload dir, creates std_document row |
| `ingestion/classifier.py` | LLM-based source_type + doc_code extraction |
| `ingestion/web_fetcher.py` | SSRF-safe, allowlist-gated, robots-respecting HTTP fetcher with manual-paste fallback |
| `ingestion/extractor_runner.py` | Dispatches to `standards/docx_extractor` or `standards/xmi_parser` based on mime |
| `analysis/__init__.py` | Package marker |
| `analysis/structurer.py` | Turns extractor output into std_clause tree + data_element + term + value_domain rows |
| `analysis/embedder.py` | Calls `embedding_gateway.get_embeddings` for clause / term / data_element; writes vector columns |
| `analysis/deduper.py` | pgvector cosine-similarity lookup against prior standards |
| `handlers.py` | Outbox event dispatch table: `extract_requested`, `structure_requested`, `embed_requested`, `dedupe_requested`, `web_snapshot_requested` |
| `tests/__init__.py` | Package marker |

**New route module:** `data_agent/api/standards_routes.py` (12 endpoints for P0)

**New migrations** (under `data_agent/migrations/`):

| File | Purpose |
|---|---|
| `070_create_extension_ltree.sql` | `CREATE EXTENSION IF NOT EXISTS ltree` + pgvector existence assertion |
| `071_std_documents_and_versions.sql` | `std_document` + `std_document_version` + indexes |
| `072_std_clauses_and_elements.sql` | `std_clause` + `std_term` + `std_data_element` + `std_value_domain` + `std_value_domain_item` + indexes |
| `073_std_references_and_snapshots.sql` | `std_reference` + `std_web_snapshot` + `std_search_session` + `std_search_hit` + indexes |
| `074_std_outbox.sql` | `std_outbox` table + indexes |
| `075_downstream_derived_link_fk.sql` | `std_derived_link` table + nullable `std_derived_link_id` on 4 downstream tables (deriving actually happens in P2; we only add the columns here) |

**New tests** (under `data_agent/standards_platform/tests/`, invoked by the project's top-level `pytest data_agent/`):

| File | Covers |
|---|---|
| `test_config.py` | env-var parsing happy path + defaults |
| `test_repository.py` | CRUD primitives round-trip |
| `test_outbox.py` | enqueue / claim / complete / fail / retry-backoff |
| `test_outbox_worker.py` | worker restart continuity, max-attempts → failed |
| `test_uploader.py` | sandboxing, duplicate-checksum reuse |
| `test_classifier.py` | source_type recognition across 4 canonical filenames (LLM mocked) |
| `test_web_fetcher.py` | allowlist, SSRF rejection, robots-disallow, size-cap, manual-paste |
| `test_extractor_runner.py` | dispatch to docx vs xmi, error capture into last_error_log |
| `test_structurer.py` | clause tree + term + data_element + value_domain extraction round-trip |
| `test_embedder.py` | dimension matches active model, batch shape, empty-on-failure |
| `test_deduper.py` | known-duplicate retrieval > threshold, unrelated < threshold |
| `test_handlers.py` | each event_type → right handler → right side-effects |
| `test_api_standards.py` | each of 12 endpoints: auth + RBAC + happy path + one error path |
| `test_migrations_070_to_075.py` | migrations apply cleanly, rollback-safe idempotence |

**New frontend files** (under `frontend/src/components/datapanel/`):

| File | Responsibility |
|---|---|
| `StandardsTab.tsx` | Top-level container with 6 sub-tab router (only 2 wired in P0, others placeholders) |
| `standards/IngestSubTab.tsx` | Upload / URL fetch / document list |
| `standards/AnalyzeSubTab.tsx` | Clause tree viewer + data-element table + similar-clause hits |
| `standards/standardsApi.ts` | Typed `fetch()` wrappers for 12 endpoints |

**Modified files:**

| File | Modification |
|---|---|
| `frontend_api.py` | Add lazy-import mount for `api/standards_routes.py` routes (pattern: like existing `domain_standard_routes` mount) |
| `frontend/src/components/DataPanel.tsx` | Import + render `StandardsTab` |
| `data_agent/.env.sample` (if exists) or document in README | New env vars |
| `docs/roadmap.md` | Add v25.x Standards Platform entry |
| `requirements.txt` | Add `python-magic-bin` (Windows mime detection), `weasyprint` deferred to P2 |
| **Pre-task commit:** `data_agent/standards/docx_extractor.py`, `docx_standard_provider.py`, `semantic_config_generator.py`, `cli.py`, `compiled/`, `compiled_docx/` | Promote from untracked to tracked (Task 1) |

---

## Conventions (read once, apply everywhere)

1. **Raw SQL, not ORM.** Use `with get_engine().connect() as conn: conn.execute(text("..."), {...}); conn.commit()`. Match the style of `audit_logger.py`.
2. **Table-name constants.** Declare at module top: `T_STD_DOCUMENT = "std_document"`, etc., then reference the constant in SQL. Matches `database_tools.py`.
3. **Logger per module.** `from .observability import get_logger` then `logger = get_logger("standards_platform.<submodule>")`.
4. **Auth on every route.** First two lines inside each async endpoint:
   ```python
   user = _get_user_from_request(request)
   if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
   username, role = _set_user_context(user)
   ```
5. **Commits are small, per-step.** Format: `feat(std-platform): <task> — <step>` — spec doc lives under `feat(std-platform):` scope too.
6. **Tests go next to the module they test**, but in a `tests/` subdir inside the package. `pytest data_agent/` discovers them via the existing rootdir.
7. **No `from data_agent.X` inside the package** — use relative imports (`from .observability import ...`) to match project style.
8. **SQL NOTIFY channel name prefix:** `std_*` (e.g., `std_version_released`).

---

## Done Criteria (P0 as a whole)

- All 14 test files pass (new); all existing project tests still pass (`pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q`).
- Migrations 070–075 apply on a clean DB and on the current dev DB.
- Uploading `GB-T-13923-2022.docx` via the UI triggers the full pipeline and within 10 minutes populates: `std_document` (status=drafting), `std_document_version`, ≥ 20 `std_clause`, ≥ 5 `std_data_element`, and embeddings on clauses.
- Uploading a second overlapping standard surfaces ≥ 80% of overlapping clauses in the Analyze-tab "similar" panel.
- `python -m data_agent.standards_platform.outbox_worker` runs independently of chainlit; killing it mid-pipeline and restarting it resumes.
- `npm run build` in `frontend/` passes.
- `docs/roadmap.md` updated.

---
## Task 1: Commit existing parser artifacts as infrastructure baseline

**Files:**
- Stage (already on disk, untracked or modified):
  - `data_agent/standards/docx_extractor.py`
  - `data_agent/standards/docx_standard_provider.py`
  - `data_agent/standards/semantic_config_generator.py`
  - `data_agent/standards/cli.py`
  - `data_agent/standards/compiled/**`
  - `data_agent/standards/compiled_docx/**`

- [ ] **Step 1: Inspect what's actually there**

Run:
```
git status -uall data_agent/standards/
git diff --stat data_agent/standards/
```

Expected: several `??` lines for the files above, plus the already-tracked `xmi_parser.py` / `xmi_compiler.py` possibly unchanged.

- [ ] **Step 2: Spot-check the untracked files compile**

Run:
```
.venv/Scripts/python.exe -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8')) for p in pathlib.Path('data_agent/standards').glob('*.py')]"
```
Expected: no output, exit 0.

- [ ] **Step 3: Stage explicitly (do not use `git add .`)**

Run:
```
git add data_agent/standards/docx_extractor.py data_agent/standards/docx_standard_provider.py data_agent/standards/semantic_config_generator.py data_agent/standards/cli.py data_agent/standards/compiled data_agent/standards/compiled_docx
```

- [ ] **Step 4: Commit**

```
git commit -m "feat(std-platform): commit docx extractor, cli, and compiled standards as infra baseline

These parser artifacts were developed earlier and left untracked.
Promote them to tracked status as the foundation for the new
standards_platform subsystem (spec 2026-05-13)."
```

## Task 2: Migration 070 — ltree extension + pgvector assertion

**Files:**
- Create: `data_agent/migrations/070_create_extension_ltree.sql`
- Test: `data_agent/standards_platform/tests/test_migrations_070_to_075.py` (created here, extended later)

- [ ] **Step 1: Write the failing test**

Create `data_agent/standards_platform/tests/__init__.py` (empty file).

Create `data_agent/standards_platform/tests/test_migrations_070_to_075.py`:
```python
"""Migration 070-075 smoke tests — applied cleanly + extensions present."""
import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine


def _has_extension(name: str) -> bool:
    eng = get_engine()
    if eng is None:
        pytest.skip("DB unavailable")
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = :n"),
            {"n": name},
        ).first()
        return row is not None


def test_ltree_extension_present_after_070():
    assert _has_extension("ltree"), "migration 070 must enable ltree"


def test_pgvector_extension_present():
    assert _has_extension("vector"), "pgvector is a system requirement"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_migrations_070_to_075.py -v`
Expected: `test_ltree_extension_present_after_070` FAILS (ltree not yet installed); `test_pgvector_extension_present` PASSES (already installed).

- [ ] **Step 3: Write the migration**

Create `data_agent/migrations/070_create_extension_ltree.sql`:
```sql
-- =============================================================================
-- Migration 070: enable ltree extension for std_clause.ordinal_path
-- =============================================================================
-- The standards_platform subsystem stores hierarchical clause paths
-- (e.g. "5.2.3") as ltree to enable subtree queries (<@, @>, ~).
-- pgvector is asserted as a system requirement (already installed 0.8.0).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS ltree;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pgvector extension is required but not installed. Install with: CREATE EXTENSION vector;';
    END IF;
END $$;
```

- [ ] **Step 4: Apply the migration**

Run: `.venv/Scripts/python.exe -m data_agent.migration_runner`
Expected stdout includes: `Applied: 070_create_extension_ltree.sql`.

- [ ] **Step 5: Re-run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_migrations_070_to_075.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Commit**

```
git add data_agent/migrations/070_create_extension_ltree.sql data_agent/standards_platform/tests/__init__.py data_agent/standards_platform/tests/test_migrations_070_to_075.py
git commit -m "feat(std-platform): migration 070 enable ltree + assert pgvector"
```

## Task 3: Migration 071 — std_document + std_document_version

**Files:**
- Create: `data_agent/migrations/071_std_documents_and_versions.sql`
- Modify: `data_agent/standards_platform/tests/test_migrations_070_to_075.py` (add asserts)

- [ ] **Step 1: Add failing assertions to the test**

Append to `data_agent/standards_platform/tests/test_migrations_070_to_075.py`:
```python
def _table_columns(table: str) -> set[str]:
    eng = get_engine()
    if eng is None:
        pytest.skip("DB unavailable")
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t"
        ), {"t": table}).fetchall()
        return {r[0] for r in rows}


def test_std_document_table_shape():
    cols = _table_columns("std_document")
    assert {"id", "doc_code", "title", "source_type", "source_url",
            "language", "status", "current_version_id", "owner_user_id",
            "tags", "raw_file_path", "last_error_log",
            "created_at", "updated_at", "created_by", "updated_by"} <= cols


def test_std_document_version_table_shape():
    cols = _table_columns("std_document_version")
    assert {"id", "document_id", "version_label",
            "semver_major", "semver_minor", "semver_patch",
            "released_at", "release_notes", "supersedes_version_id",
            "status", "snapshot_blob",
            "created_at", "updated_at", "created_by", "updated_by"} <= cols
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_migrations_070_to_075.py::test_std_document_table_shape -v`
Expected: FAIL (table does not exist).

- [ ] **Step 3: Write migration 071**

Create `data_agent/migrations/071_std_documents_and_versions.sql`:
```sql
-- =============================================================================
-- Migration 071: std_document + std_document_version
-- =============================================================================

CREATE TABLE IF NOT EXISTS std_document (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    doc_code            TEXT NOT NULL,
    title               TEXT NOT NULL,
    source_type         TEXT NOT NULL
                            CHECK (source_type IN (
                                'national','industry','enterprise',
                                'international','draft')),
    source_url          TEXT,
    language            TEXT DEFAULT 'zh-CN',
    status              TEXT NOT NULL DEFAULT 'ingested'
                            CHECK (status IN (
                                'ingested','drafting','reviewing',
                                'published','superseded','archived')),
    current_version_id  UUID,
    owner_user_id       TEXT NOT NULL,
    tags                TEXT[] DEFAULT '{}',
    raw_file_path       TEXT,
    last_error_log      JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          TEXT,
    updated_by          TEXT,
    UNIQUE (doc_code, source_type)
);

CREATE INDEX IF NOT EXISTS idx_std_document_status ON std_document(status);
CREATE INDEX IF NOT EXISTS idx_std_document_owner ON std_document(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_std_document_source_type ON std_document(source_type);
```
(continued in step 4)

- [ ] **Step 4: Append std_document_version to 071**

Append to `data_agent/migrations/071_std_documents_and_versions.sql`:
```sql
CREATE TABLE IF NOT EXISTS std_document_version (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id             UUID NOT NULL REFERENCES std_document(id) ON DELETE CASCADE,
    version_label           TEXT NOT NULL,
    semver_major            INT NOT NULL,
    semver_minor            INT NOT NULL DEFAULT 0,
    semver_patch            INT NOT NULL DEFAULT 0,
    released_at             TIMESTAMPTZ,
    release_notes           TEXT,
    supersedes_version_id   UUID REFERENCES std_document_version(id),
    status                  TEXT NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft','review','approved','released','retired')),
    snapshot_blob           JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by              TEXT,
    updated_by              TEXT,
    UNIQUE (document_id, version_label)
);

CREATE INDEX IF NOT EXISTS idx_std_docver_doc ON std_document_version(document_id);
CREATE INDEX IF NOT EXISTS idx_std_docver_status ON std_document_version(status);

ALTER TABLE std_document
    ADD CONSTRAINT fk_std_document_current_version
    FOREIGN KEY (current_version_id) REFERENCES std_document_version(id)
    DEFERRABLE INITIALLY DEFERRED;
```

- [ ] **Step 5: Apply and verify**

Run:
```
.venv/Scripts/python.exe -m data_agent.migration_runner
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_migrations_070_to_075.py -v
```
Expected: migration applied; all tests PASS.

- [ ] **Step 6: Commit**

```
git add data_agent/migrations/071_std_documents_and_versions.sql data_agent/standards_platform/tests/test_migrations_070_to_075.py
git commit -m "feat(std-platform): migration 071 std_document + std_document_version"
```

## Task 4: Migration 072 — clauses, terms, data_elements, value_domains

**Files:**
- Create: `data_agent/migrations/072_std_clauses_and_elements.sql`
- Modify: `data_agent/standards_platform/tests/test_migrations_070_to_075.py`

- [ ] **Step 1: Extend the test with shape assertions**

Append:
```python
def test_std_clause_shape_and_vector_dim():
    cols = _table_columns("std_clause")
    assert {"id","document_id","document_version_id","parent_clause_id",
            "ordinal_path","heading","clause_no","kind","body_md","body_html",
            "checksum","lock_holder","lock_expires_at","source_origin",
            "embedding"} <= cols
    eng = get_engine()
    with eng.connect() as conn:
        dim = conn.execute(text(
            "SELECT atttypmod FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
            "WHERE c.relname='std_clause' AND a.attname='embedding'"
        )).scalar()
        assert dim == 768, f"embedding dim must be 768, got {dim}"


def test_std_data_element_shape():
    cols = _table_columns("std_data_element")
    assert {"id","document_version_id","code","name_zh","name_en","definition",
            "representation_class","datatype","unit","value_domain_id",
            "obligation","cardinality","defined_by_clause_id","term_id",
            "data_classification","embedding"} <= cols


def test_std_value_domain_shape():
    cols = _table_columns("std_value_domain")
    assert {"id","document_version_id","code","name","kind",
            "defined_by_clause_id"} <= cols
    cols2 = _table_columns("std_value_domain_item")
    assert {"id","value_domain_id","value","label_zh","label_en","ordinal"} <= cols2


def test_std_term_shape():
    cols = _table_columns("std_term")
    assert {"id","document_version_id","term_code","name_zh","name_en",
            "definition","aliases","defined_by_clause_id","embedding"} <= cols
```

Run and confirm all FAIL.

- [ ] **Step 2: Write migration 072**

Create `data_agent/migrations/072_std_clauses_and_elements.sql`:
```sql
-- Migration 072: clause tree + data elements + value domains + terms.
-- Embedding dimension is pinned to 768 (embedding_gateway default).

CREATE TABLE IF NOT EXISTS std_clause (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id             UUID NOT NULL REFERENCES std_document(id) ON DELETE CASCADE,
    document_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    parent_clause_id        UUID REFERENCES std_clause(id) ON DELETE CASCADE,
    ordinal_path            LTREE NOT NULL,
    heading                 TEXT,
    clause_no               TEXT,
    kind                    TEXT NOT NULL
                                CHECK (kind IN ('chapter','section','clause','paragraph',
                                    'definition','requirement','example','note','figure','table')),
    body_md                 TEXT DEFAULT '',
    body_html               TEXT,
    checksum                TEXT,
    lock_holder             TEXT,
    lock_expires_at         TIMESTAMPTZ,
    source_origin           JSONB,
    embedding               VECTOR(768),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by              TEXT,
    updated_by              TEXT,
    UNIQUE (document_version_id, ordinal_path)
);
CREATE INDEX IF NOT EXISTS idx_std_clause_path ON std_clause USING GIST (ordinal_path);
CREATE INDEX IF NOT EXISTS idx_std_clause_parent ON std_clause(parent_clause_id);
CREATE INDEX IF NOT EXISTS idx_std_clause_docver ON std_clause(document_version_id);

CREATE TABLE IF NOT EXISTS std_term (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    term_code               TEXT NOT NULL,
    name_zh                 TEXT NOT NULL,
    name_en                 TEXT,
    definition              TEXT,
    aliases                 TEXT[] DEFAULT '{}',
    defined_by_clause_id    UUID REFERENCES std_clause(id) ON DELETE SET NULL,
    embedding               VECTOR(768),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, term_code)
);
```
(continued)

- [ ] **Step 3: Append value domains + data elements to 072**

Append to `data_agent/migrations/072_std_clauses_and_elements.sql`:
```sql
CREATE TABLE IF NOT EXISTS std_value_domain (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    code                    TEXT NOT NULL,
    name                    TEXT NOT NULL,
    kind                    TEXT NOT NULL
                                CHECK (kind IN ('enumeration','range','pattern','external_codelist')),
    defined_by_clause_id    UUID REFERENCES std_clause(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, code)
);

CREATE TABLE IF NOT EXISTS std_value_domain_item (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    value_domain_id         UUID NOT NULL REFERENCES std_value_domain(id) ON DELETE CASCADE,
    value                   TEXT NOT NULL,
    label_zh                TEXT,
    label_en                TEXT,
    ordinal                 INT NOT NULL DEFAULT 0,
    UNIQUE (value_domain_id, value),
    UNIQUE (value_domain_id, ordinal)
);

CREATE TABLE IF NOT EXISTS std_data_element (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    code                    TEXT NOT NULL,
    name_zh                 TEXT NOT NULL,
    name_en                 TEXT,
    definition              TEXT,
    representation_class    TEXT
                                CHECK (representation_class IN
                                    ('code','text','integer','decimal','datetime','geometry','boolean')),
    datatype                TEXT,
    unit                    TEXT,
    value_domain_id         UUID REFERENCES std_value_domain(id) ON DELETE SET NULL,
    obligation              TEXT NOT NULL DEFAULT 'optional'
                                CHECK (obligation IN ('mandatory','conditional','optional')),
    cardinality             TEXT DEFAULT '1',
    defined_by_clause_id    UUID REFERENCES std_clause(id) ON DELETE SET NULL,
    term_id                 UUID REFERENCES std_term(id) ON DELETE SET NULL,
    data_classification     TEXT,
    embedding               VECTOR(768),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, code)
);
CREATE INDEX IF NOT EXISTS idx_std_data_element_docver ON std_data_element(document_version_id);
```

- [ ] **Step 4: Apply + test + commit**

Run `.venv/Scripts/python.exe -m data_agent.migration_runner` then the test file; all new assertions pass.
```
git add data_agent/migrations/072_std_clauses_and_elements.sql data_agent/standards_platform/tests/test_migrations_070_to_075.py
git commit -m "feat(std-platform): migration 072 clauses, terms, data elements, value domains"
```

## Task 5: Migration 073 — references, web snapshots, search sessions

**Files:**
- Create: `data_agent/migrations/073_std_references_and_snapshots.sql`
- Modify: `data_agent/standards_platform/tests/test_migrations_070_to_075.py`

- [ ] **Step 1: Add shape tests (run, confirm fail)**

Append to the test file:
```python
def test_std_reference_shape():
    cols = _table_columns("std_reference")
    assert {"id","source_clause_id","source_data_element_id","target_kind",
            "target_clause_id","target_document_id","target_url","target_doi",
            "snapshot_id","citation_text","confidence","verified_by",
            "verified_at"} <= cols


def test_std_web_snapshot_shape():
    cols = _table_columns("std_web_snapshot")
    assert {"id","url","http_status","fetched_at","html_path","pdf_path",
            "extracted_text","search_query"} <= cols


def test_std_search_session_and_hit():
    assert {"id","document_version_id","clause_id","author_user_id",
            "messages","created_at"} <= _table_columns("std_search_session")
    assert {"id","session_id","query","rank","snapshot_id","snippet"} \
        <= _table_columns("std_search_hit")
```

- [ ] **Step 2: Write migration 073**

Create `data_agent/migrations/073_std_references_and_snapshots.sql`:
```sql
CREATE TABLE IF NOT EXISTS std_web_snapshot (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    url             TEXT NOT NULL,
    http_status     INT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    html_path       TEXT,
    pdf_path        TEXT,
    extracted_text  TEXT,
    search_query    TEXT
);
CREATE INDEX IF NOT EXISTS idx_std_web_snapshot_url ON std_web_snapshot(url);

CREATE TABLE IF NOT EXISTS std_reference (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_clause_id         UUID REFERENCES std_clause(id) ON DELETE CASCADE,
    source_data_element_id   UUID REFERENCES std_data_element(id) ON DELETE CASCADE,
    target_kind              TEXT NOT NULL
                                 CHECK (target_kind IN (
                                     'std_clause','std_document',
                                     'external_url','web_snapshot','internet_search')),
    target_clause_id         UUID REFERENCES std_clause(id) ON DELETE SET NULL,
    target_document_id       UUID REFERENCES std_document(id) ON DELETE SET NULL,
    target_url               TEXT,
    target_doi               TEXT,
    snapshot_id              UUID REFERENCES std_web_snapshot(id) ON DELETE SET NULL,
    citation_text            TEXT NOT NULL,
    confidence               NUMERIC(3,2),
    verified_by              TEXT,
    verified_at              TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_clause_id IS NOT NULL OR source_data_element_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_std_reference_src_clause ON std_reference(source_clause_id);
CREATE INDEX IF NOT EXISTS idx_std_reference_src_de ON std_reference(source_data_element_id);
```
(continued)

- [ ] **Step 3: Append search sessions to 073**

Append:
```sql
CREATE TABLE IF NOT EXISTS std_search_session (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_version_id  UUID REFERENCES std_document_version(id) ON DELETE CASCADE,
    clause_id            UUID REFERENCES std_clause(id) ON DELETE CASCADE,
    author_user_id       TEXT NOT NULL,
    messages             JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS std_search_hit (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id   UUID NOT NULL REFERENCES std_search_session(id) ON DELETE CASCADE,
    query        TEXT NOT NULL,
    rank         INT NOT NULL,
    snapshot_id  UUID REFERENCES std_web_snapshot(id) ON DELETE SET NULL,
    snippet      TEXT
);
```

- [ ] **Step 4: Apply + test + commit**

```
.venv/Scripts/python.exe -m data_agent.migration_runner
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_migrations_070_to_075.py -v
git add data_agent/migrations/073_std_references_and_snapshots.sql data_agent/standards_platform/tests/test_migrations_070_to_075.py
git commit -m "feat(std-platform): migration 073 references, web snapshots, search sessions"
```

## Task 6: Migration 074 — std_outbox

**Files:**
- Create: `data_agent/migrations/074_std_outbox.sql`
- Modify: `data_agent/standards_platform/tests/test_migrations_070_to_075.py`

- [ ] **Step 1: Add failing test**

Append:
```python
def test_std_outbox_shape():
    cols = _table_columns("std_outbox")
    assert {"id","event_type","payload","created_at","processed_at",
            "attempts","last_error","next_attempt_at","status"} <= cols

def test_std_outbox_partial_index_pending():
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'std_outbox'"
        )).fetchall()
        names = {r[0] for r in rows}
    assert "idx_std_outbox_pending" in names
```

- [ ] **Step 2: Write migration 074**

Create `data_agent/migrations/074_std_outbox.sql`:
```sql
CREATE TABLE IF NOT EXISTS std_outbox (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type        TEXT NOT NULL
                          CHECK (event_type IN (
                              'extract_requested','structure_requested',
                              'embed_requested','dedupe_requested',
                              'web_snapshot_requested','version_released',
                              'clause_updated','derivation_requested',
                              'invalidation_needed')),
    payload           JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at      TIMESTAMPTZ,
    attempts          INT NOT NULL DEFAULT 0,
    last_error        TEXT,
    next_attempt_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status            TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','in_flight','done','failed'))
);

CREATE INDEX IF NOT EXISTS idx_std_outbox_pending
    ON std_outbox(next_attempt_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_std_outbox_status ON std_outbox(status);
```

- [ ] **Step 3: Apply + test + commit**

```
.venv/Scripts/python.exe -m data_agent.migration_runner
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_migrations_070_to_075.py -v
git add data_agent/migrations/074_std_outbox.sql data_agent/standards_platform/tests/test_migrations_070_to_075.py
git commit -m "feat(std-platform): migration 074 std_outbox"
```

## Task 7: Migration 075 — std_derived_link + downstream FK columns

**Files:**
- Create: `data_agent/migrations/075_downstream_derived_link_fk.sql`
- Modify: `data_agent/standards_platform/tests/test_migrations_070_to_075.py`

> **Note:** Derivation logic itself is P2. This task only adds the schema so future derive-phase code can slot in. The four downstream tables receive a NULLABLE `std_derived_link_id` column — existing rows are untouched.

- [ ] **Step 1: Add shape tests (run, confirm fail)**

Append:
```python
def test_std_derived_link_shape():
    cols = _table_columns("std_derived_link")
    assert {"id","source_kind","source_id","source_version_id","target_kind",
            "target_table","target_id","derivation_strategy","status",
            "stale_reason","generated_at"} <= cols


def test_downstream_tables_have_derived_link_fk():
    for t in ("agent_semantic_hints","sources_synonyms",
              "value_semantics","qc_rules"):
        eng = get_engine()
        if eng is None:
            pytest.skip("DB unavailable")
        with eng.connect() as conn:
            exists = conn.execute(text(
                "SELECT to_regclass(:t)"
            ), {"t": t}).scalar()
            if exists is None:
                pytest.skip(f"{t} not in this deployment")
            cols = _table_columns(t)
            assert "std_derived_link_id" in cols, f"{t} missing FK column"
```

- [ ] **Step 2: Inspect actual downstream table names**

Before writing the migration, verify the real names of the four downstream targets in this DB:
```
.venv/Scripts/python.exe -c "from data_agent.db_engine import get_engine; from sqlalchemy import text; eng=get_engine();
import json
with eng.connect() as c:
    for hint in ('semantic_hint','value_semantic','synonym','qc_rule','qc_rules','defect'):
        rows=c.execute(text(\"SELECT table_schema,table_name FROM information_schema.tables WHERE table_name ILIKE :p\"), {'p':f'%{hint}%'}).fetchall()
        print(hint, rows)
"
```
Record actual names; update Task 7 Step 3 migration DDL if a table is named differently than the test assumes (e.g. `value_semantics` may live inside `agent_semantic_registry` as a column, not its own table — in that case drop that FK from this migration and note it in the commit message).

- [ ] **Step 3: Write migration 075 (adjust per Step 2 findings)**

Create `data_agent/migrations/075_downstream_derived_link_fk.sql`:
```sql
-- Migration 075: std_derived_link table + FK columns on downstream tables.
-- Derivation engine lives in P2; only schema is added here.
-- The ALTER statements are guarded with IF NOT EXISTS / DO blocks so re-runs
-- and partial deployments are safe.

CREATE TABLE IF NOT EXISTS std_derived_link (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_kind           TEXT NOT NULL
                              CHECK (source_kind IN ('clause','data_element','value_domain','term')),
    source_id             UUID NOT NULL,
    source_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    target_kind           TEXT NOT NULL
                              CHECK (target_kind IN (
                                  'semantic_hint','value_semantic','synonym',
                                  'qc_rule','defect_code','data_model_attribute',
                                  'table_column')),
    target_table          TEXT NOT NULL,
    target_id             TEXT NOT NULL,
    derivation_strategy   TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','active','stale','overridden','superseded')),
    stale_reason          TEXT,
    generated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_std_derived_link_active
    ON std_derived_link(target_kind, target_table, target_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_std_derived_link_source
    ON std_derived_link(source_kind, source_id);

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'agent_semantic_hints',
        'sources_synonyms',
        'qc_rules'
    ]
    LOOP
        IF to_regclass(tbl) IS NOT NULL THEN
            EXECUTE format(
                'ALTER TABLE %I ADD COLUMN IF NOT EXISTS std_derived_link_id UUID REFERENCES std_derived_link(id) ON DELETE SET NULL',
                tbl
            );
            EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%I_derived_link ON %I(std_derived_link_id)', tbl, tbl);
        END IF;
    END LOOP;
END $$;
```

- [ ] **Step 4: Apply + test + commit**

```
.venv/Scripts/python.exe -m data_agent.migration_runner
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_migrations_070_to_075.py -v
git add data_agent/migrations/075_downstream_derived_link_fk.sql data_agent/standards_platform/tests/test_migrations_070_to_075.py
git commit -m "feat(std-platform): migration 075 std_derived_link + downstream FK columns"
```

## Task 8: Package skeleton + config module

**Files:**
- Create: `data_agent/standards_platform/__init__.py`
- Create: `data_agent/standards_platform/config.py`
- Create: `data_agent/standards_platform/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `data_agent/standards_platform/tests/test_config.py`:
```python
import os
from data_agent.standards_platform.config import StandardsConfig


def test_defaults_when_env_missing(monkeypatch):
    for k in ("STANDARDS_WEB_DOMAINS_ALLOWLIST",
              "STANDARDS_OUTBOX_WORKER_INTERVAL_SEC",
              "STANDARDS_OUTBOX_MAX_ATTEMPTS"):
        monkeypatch.delenv(k, raising=False)
    cfg = StandardsConfig.from_env()
    assert cfg.outbox_worker_interval_sec == 5
    assert cfg.outbox_max_attempts == 5
    assert "std.samr.gov.cn" in cfg.web_domains_allowlist
    assert "openstd.samr.gov.cn" in cfg.web_domains_allowlist
    assert "ogc.org" in cfg.web_domains_allowlist
    assert "iso.org" in cfg.web_domains_allowlist
    assert "arxiv.org" in cfg.web_domains_allowlist
    assert "scholar.google.com" in cfg.web_domains_allowlist
    assert "cnki.net" in cfg.web_domains_allowlist


def test_overrides_from_env(monkeypatch):
    monkeypatch.setenv("STANDARDS_WEB_DOMAINS_ALLOWLIST", "example.com,foo.org")
    monkeypatch.setenv("STANDARDS_OUTBOX_WORKER_INTERVAL_SEC", "12")
    monkeypatch.setenv("STANDARDS_OUTBOX_MAX_ATTEMPTS", "9")
    cfg = StandardsConfig.from_env()
    assert cfg.web_domains_allowlist == {"example.com", "foo.org"}
    assert cfg.outbox_worker_interval_sec == 12
    assert cfg.outbox_max_attempts == 9
```

Run: `.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_config.py -v`
Expected: ImportError fail.

- [ ] **Step 2: Implement config + package skeleton**

Create `data_agent/standards_platform/__init__.py`:
```python
"""Standards Platform — data-standard lifecycle management.

P0 scope: ingest + analyze. See spec
docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md
"""
__version__ = "0.1.0"
```

Create `data_agent/standards_platform/config.py`:
```python
"""Env-driven configuration for the standards_platform subsystem."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_ALLOWLIST = (
    "std.samr.gov.cn",
    "openstd.samr.gov.cn",
    "ogc.org",
    "iso.org",
    "arxiv.org",
    "scholar.google.com",
    "cnki.net",
)


@dataclass(frozen=True)
class StandardsConfig:
    web_domains_allowlist: frozenset[str] = field(default_factory=lambda: frozenset(DEFAULT_ALLOWLIST))
    outbox_worker_interval_sec: int = 5
    outbox_max_attempts: int = 5
    web_max_bytes: int = 10 * 1024 * 1024  # 10 MB
    rate_limit_per_minute: int = 20

    @classmethod
    def from_env(cls) -> "StandardsConfig":
        raw = os.getenv("STANDARDS_WEB_DOMAINS_ALLOWLIST", "")
        if raw.strip():
            allow = frozenset(d.strip() for d in raw.split(",") if d.strip())
        else:
            allow = frozenset(DEFAULT_ALLOWLIST)
        return cls(
            web_domains_allowlist=allow,
            outbox_worker_interval_sec=int(os.getenv("STANDARDS_OUTBOX_WORKER_INTERVAL_SEC", "5")),
            outbox_max_attempts=int(os.getenv("STANDARDS_OUTBOX_MAX_ATTEMPTS", "5")),
        )
```

- [ ] **Step 3: Run + commit**

Run: `.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_config.py -v` → PASS.
```
git add data_agent/standards_platform/__init__.py data_agent/standards_platform/config.py data_agent/standards_platform/tests/test_config.py
git commit -m "feat(std-platform): config module + package skeleton"
```

## Task 9: Outbox primitives — enqueue, claim, complete, fail

**Files:**
- Create: `data_agent/standards_platform/outbox.py`
- Create: `data_agent/standards_platform/tests/test_outbox.py`

- [ ] **Step 1: Write the failing test**

Create `data_agent/standards_platform/tests/test_outbox.py`:
```python
import uuid
import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine
from data_agent.standards_platform import outbox as ob


@pytest.fixture
def clean_outbox():
    eng = get_engine()
    if eng is None:
        pytest.skip("DB unavailable")
    with eng.connect() as conn:
        conn.execute(text("DELETE FROM std_outbox"))
        conn.commit()
    yield eng


def test_enqueue_creates_pending_row(clean_outbox):
    evt_id = ob.enqueue("extract_requested", {"doc_id": str(uuid.uuid4())})
    with clean_outbox.connect() as conn:
        row = conn.execute(text("SELECT status, attempts FROM std_outbox WHERE id = :i"),
                           {"i": evt_id}).first()
    assert row.status == "pending"
    assert row.attempts == 0


def test_claim_marks_in_flight(clean_outbox):
    evt_id = ob.enqueue("embed_requested", {"clause_id": "x"})
    claimed = ob.claim_batch(limit=1)
    assert len(claimed) == 1
    assert claimed[0]["id"] == evt_id
    with clean_outbox.connect() as conn:
        status = conn.execute(text("SELECT status FROM std_outbox WHERE id = :i"),
                              {"i": evt_id}).scalar()
    assert status == "in_flight"


def test_complete_marks_done(clean_outbox):
    evt_id = ob.enqueue("dedupe_requested", {"doc_id": "y"})
    ob.claim_batch(limit=1)
    ob.complete(evt_id)
    with clean_outbox.connect() as conn:
        status = conn.execute(text("SELECT status, processed_at FROM std_outbox WHERE id = :i"),
                              {"i": evt_id}).first()
    assert status.status == "done"
    assert status.processed_at is not None


def test_fail_increments_attempts_and_schedules_retry(clean_outbox):
    evt_id = ob.enqueue("structure_requested", {"doc_id": "z"})
    ob.claim_batch(limit=1)
    ob.fail(evt_id, "boom", max_attempts=5)
    with clean_outbox.connect() as conn:
        row = conn.execute(text(
            "SELECT status, attempts, last_error FROM std_outbox WHERE id = :i"
        ), {"i": evt_id}).first()
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.last_error == "boom"


def test_fail_after_max_attempts_marks_failed(clean_outbox):
    evt_id = ob.enqueue("structure_requested", {"doc_id": "z"})
    for _ in range(5):
        ob.claim_batch(limit=1)
        ob.fail(evt_id, "persist", max_attempts=5)
    with clean_outbox.connect() as conn:
        row = conn.execute(text(
            "SELECT status, attempts FROM std_outbox WHERE id = :i"
        ), {"i": evt_id}).first()
    assert row.status == "failed"
    assert row.attempts == 5


def test_claim_skips_not_yet_due(clean_outbox):
    """next_attempt_at in the future must not be claimed."""
    evt_id = ob.enqueue("extract_requested", {"doc_id": "future"})
    with clean_outbox.connect() as conn:
        conn.execute(text(
            "UPDATE std_outbox SET next_attempt_at = now() + interval '1 hour' WHERE id = :i"
        ), {"i": evt_id})
        conn.commit()
    assert ob.claim_batch(limit=5) == []
```

Run: `.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_outbox.py -v` → all FAIL (module missing).

- [ ] **Step 2: Implement outbox**

Create `data_agent/standards_platform/outbox.py`:
```python
"""Outbox primitives — at-least-once event delivery backed by std_outbox table.

Safe for multi-worker deployment via SELECT ... FOR UPDATE SKIP LOCKED.
"""
from __future__ import annotations

import json
import uuid
from typing import Iterable

from sqlalchemy import text

from ..db_engine import get_engine
from ..observability import get_logger

logger = get_logger("standards_platform.outbox")

# Allowed event types — mirror std_outbox CHECK constraint.
EVENT_TYPES = frozenset({
    "extract_requested", "structure_requested", "embed_requested",
    "dedupe_requested", "web_snapshot_requested", "version_released",
    "clause_updated", "derivation_requested", "invalidation_needed",
})


def enqueue(event_type: str, payload: dict) -> str:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event_type {event_type!r}")
    evt_id = str(uuid.uuid4())
    eng = get_engine()
    if eng is None:
        raise RuntimeError("DB engine unavailable")
    with eng.connect() as conn:
        conn.execute(text(
            "INSERT INTO std_outbox (id, event_type, payload) "
            "VALUES (:i, :e, CAST(:p AS jsonb))"
        ), {"i": evt_id, "e": event_type,
            "p": json.dumps(payload, ensure_ascii=False)})
        conn.commit()
    return evt_id


def claim_batch(limit: int = 10) -> list[dict]:
    """Atomically claim up to `limit` pending events that are due."""
    eng = get_engine()
    if eng is None:
        return []
    with eng.connect() as conn:
        rows = conn.execute(text("""
            UPDATE std_outbox
               SET status = 'in_flight'
             WHERE id IN (
                 SELECT id FROM std_outbox
                  WHERE status = 'pending'
                    AND next_attempt_at <= now()
                  ORDER BY next_attempt_at
                  LIMIT :lim
                  FOR UPDATE SKIP LOCKED
             )
         RETURNING id, event_type, payload, attempts
        """), {"lim": limit}).mappings().all()
        conn.commit()
        return [dict(r) for r in rows]
```
(continued)

- [ ] **Step 3: Implement complete/fail helpers**

Append to `data_agent/standards_platform/outbox.py`:
```python
def complete(evt_id: str) -> None:
    eng = get_engine()
    if eng is None:
        return
    with eng.connect() as conn:
        conn.execute(text(
            "UPDATE std_outbox SET status='done', processed_at=now() WHERE id=:i"
        ), {"i": evt_id})
        conn.commit()


def fail(evt_id: str, error: str, *, max_attempts: int = 5) -> None:
    """Increment attempts; schedule retry with exponential backoff; or mark failed."""
    eng = get_engine()
    if eng is None:
        return
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT attempts FROM std_outbox WHERE id=:i FOR UPDATE"
        ), {"i": evt_id}).first()
        if row is None:
            return
        attempts = row.attempts + 1
        if attempts >= max_attempts:
            conn.execute(text("""
                UPDATE std_outbox
                   SET status='failed', attempts=:a, last_error=:e,
                       processed_at=now()
                 WHERE id=:i
            """), {"i": evt_id, "a": attempts, "e": error[:2000]})
        else:
            # Exponential backoff: 2^attempts * 30s, capped at 1h.
            conn.execute(text("""
                UPDATE std_outbox
                   SET status='pending', attempts=:a, last_error=:e,
                       next_attempt_at = now() + (LEAST(3600, POWER(2, :a) * 30) || ' seconds')::interval
                 WHERE id=:i
            """), {"i": evt_id, "a": attempts, "e": error[:2000]})
        conn.commit()
```

- [ ] **Step 4: Run + commit**

Run: `.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_outbox.py -v` → all PASS.
```
git add data_agent/standards_platform/outbox.py data_agent/standards_platform/tests/test_outbox.py
git commit -m "feat(std-platform): outbox primitives (enqueue/claim/complete/fail)"
```

## Task 10: Repository — CRUD primitives over std_* tables

**Files:**
- Create: `data_agent/standards_platform/repository.py`
- Create: `data_agent/standards_platform/tests/test_repository.py`

- [ ] **Step 1: Failing test**

Create `data_agent/standards_platform/tests/test_repository.py`:
```python
import uuid
import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine
from data_agent.standards_platform import repository as repo


@pytest.fixture
def fresh_doc():
    eng = get_engine()
    if eng is None:
        pytest.skip("DB unavailable")
    code = f"TEST-{uuid.uuid4().hex[:8]}"
    yield code
    with eng.connect() as conn:
        conn.execute(text(
            "DELETE FROM std_document WHERE doc_code = :c"
        ), {"c": code})
        conn.commit()


def test_create_document_and_initial_version(fresh_doc):
    doc_id = repo.create_document(
        doc_code=fresh_doc, title="测试标准", source_type="enterprise",
        owner_user_id="tester", raw_file_path="/tmp/x.docx",
    )
    assert isinstance(doc_id, str)
    ver_id = repo.create_version(document_id=doc_id, version_label="v1.0",
                                 created_by="tester")
    repo.set_current_version(doc_id, ver_id)
    doc = repo.get_document(doc_id)
    assert doc["doc_code"] == fresh_doc
    assert doc["current_version_id"] == ver_id


def test_list_documents_filters_by_owner(fresh_doc):
    repo.create_document(doc_code=fresh_doc, title="t", source_type="enterprise",
                          owner_user_id="alice", raw_file_path="/tmp/a")
    rows = repo.list_documents(owner_user_id="alice")
    codes = {r["doc_code"] for r in rows}
    assert fresh_doc in codes


def test_get_document_returns_none_for_missing():
    assert repo.get_document(str(uuid.uuid4())) is None
```

Run, confirm fail.

- [ ] **Step 2: Implement repository**

Create `data_agent/standards_platform/repository.py`:
```python
"""Thin CRUD helpers over std_* tables. Raw SQL, returns plain dicts."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text

from ..db_engine import get_engine
from ..observability import get_logger

logger = get_logger("standards_platform.repository")


def create_document(*, doc_code: str, title: str, source_type: str,
                    owner_user_id: str, raw_file_path: str,
                    source_url: Optional[str] = None,
                    language: str = "zh-CN",
                    tags: Optional[list[str]] = None) -> str:
    doc_id = str(uuid.uuid4())
    eng = get_engine()
    with eng.connect() as conn:
        conn.execute(text("""
            INSERT INTO std_document
                (id, doc_code, title, source_type, source_url, language,
                 owner_user_id, raw_file_path, tags, created_by, updated_by)
            VALUES (:id, :code, :title, :st, :url, :lang,
                    :owner, :path, :tags, :owner, :owner)
        """), {"id": doc_id, "code": doc_code, "title": title, "st": source_type,
                "url": source_url, "lang": language, "owner": owner_user_id,
                "path": raw_file_path, "tags": tags or []})
        conn.commit()
    return doc_id


def create_version(*, document_id: str, version_label: str,
                   created_by: str, semver_major: int = 1,
                   semver_minor: int = 0, semver_patch: int = 0) -> str:
    ver_id = str(uuid.uuid4())
    eng = get_engine()
    with eng.connect() as conn:
        conn.execute(text("""
            INSERT INTO std_document_version
                (id, document_id, version_label, semver_major,
                 semver_minor, semver_patch, status, created_by, updated_by)
            VALUES (:id, :doc, :lbl, :ma, :mi, :pa, 'draft', :u, :u)
        """), {"id": ver_id, "doc": document_id, "lbl": version_label,
                "ma": semver_major, "mi": semver_minor, "pa": semver_patch,
                "u": created_by})
        conn.commit()
    return ver_id


def set_current_version(document_id: str, version_id: str) -> None:
    eng = get_engine()
    with eng.connect() as conn:
        conn.execute(text(
            "UPDATE std_document SET current_version_id=:v, updated_at=now() WHERE id=:d"
        ), {"v": version_id, "d": document_id})
        conn.commit()
```
(continued)

- [ ] **Step 3: Append read helpers**

Append to `repository.py`:
```python
def get_document(document_id: str) -> Optional[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT * FROM std_document WHERE id = :i"
        ), {"i": document_id}).mappings().first()
        return dict(row) if row else None


def list_documents(*, owner_user_id: Optional[str] = None,
                   status: Optional[str] = None,
                   limit: int = 100) -> list[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        clauses = []
        params: dict = {"lim": limit}
        if owner_user_id is not None:
            clauses.append("owner_user_id = :o")
            params["o"] = owner_user_id
        if status is not None:
            clauses.append("status = :s")
            params["s"] = status
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(text(
            f"SELECT * FROM std_document {where} ORDER BY created_at DESC LIMIT :lim"
        ), params).mappings().all()
        return [dict(r) for r in rows]


def update_document_status(document_id: str, status: str,
                           *, last_error: Optional[dict] = None) -> None:
    eng = get_engine()
    with eng.connect() as conn:
        if last_error is not None:
            import json
            conn.execute(text("""
                UPDATE std_document SET status=:s, last_error_log=CAST(:e AS jsonb),
                       updated_at=now() WHERE id=:i
            """), {"s": status, "e": json.dumps(last_error, ensure_ascii=False),
                    "i": document_id})
        else:
            conn.execute(text(
                "UPDATE std_document SET status=:s, updated_at=now() WHERE id=:i"
            ), {"s": status, "i": document_id})
        conn.commit()
```

- [ ] **Step 4: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_repository.py -v
git add data_agent/standards_platform/repository.py data_agent/standards_platform/tests/test_repository.py
git commit -m "feat(std-platform): repository CRUD primitives for std_document(_version)"
```

## Task 11: Uploader — ingest docx/xmi, create document + version, enqueue extract

**Files:**
- Create: `data_agent/standards_platform/ingestion/__init__.py` (empty)
- Create: `data_agent/standards_platform/ingestion/uploader.py`
- Create: `data_agent/standards_platform/tests/test_uploader.py`

- [ ] **Step 1: Failing test**

Create `data_agent/standards_platform/tests/test_uploader.py`:
```python
import io
import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine
from data_agent.standards_platform.ingestion.uploader import ingest_upload
from data_agent.user_context import current_user_id


@pytest.fixture
def db():
    eng = get_engine()
    if eng is None: pytest.skip("DB unavailable")
    yield eng
    with eng.connect() as c:
        c.execute(text("DELETE FROM std_document WHERE owner_user_id = 'u_test'"))
        c.commit()


def test_ingest_docx_creates_document_and_version(db, tmp_path):
    current_user_id.set("u_test")
    path = tmp_path / "GB-T-XXXXX-2022.docx"
    path.write_bytes(b"PK\x03\x04 fake-docx")
    doc_id, ver_id = ingest_upload(path, original_name="GB-T-XXXXX-2022.docx")
    with db.connect() as c:
        row = c.execute(text(
            "SELECT status, source_type, current_version_id FROM std_document WHERE id=:i"
        ), {"i": doc_id}).first()
    assert row.status == "ingested"
    assert row.current_version_id == ver_id


def test_ingest_rejects_unknown_extension(tmp_path):
    current_user_id.set("u_test")
    path = tmp_path / "notes.txt"
    path.write_text("hi")
    with pytest.raises(ValueError, match="unsupported file type"):
        ingest_upload(path, original_name="notes.txt")


def test_ingest_enqueues_extract_event(db, tmp_path):
    current_user_id.set("u_test")
    path = tmp_path / "a.xmi"; path.write_text("<XMI></XMI>")
    doc_id, _ = ingest_upload(path, original_name="a.xmi")
    with db.connect() as c:
        row = c.execute(text(
            "SELECT event_type, payload FROM std_outbox "
            "WHERE payload->>'document_id' = :d"
        ), {"d": doc_id}).first()
    assert row.event_type == "extract_requested"
```

- [ ] **Step 2: Implement uploader**

Create `data_agent/standards_platform/ingestion/__init__.py` (empty).

Create `data_agent/standards_platform/ingestion/uploader.py`:
```python
"""File-upload intake: place in user sandbox, create std_document + initial version,
enqueue extract_requested event."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from ...observability import get_logger
from ...user_context import current_user_id, get_user_upload_dir
from .. import outbox, repository

logger = get_logger("standards_platform.ingestion.uploader")

SUPPORTED_EXT = {".docx", ".xmi", ".pdf"}


def ingest_upload(file_path: Path, *, original_name: str,
                  source_type: str = "enterprise",
                  source_url: str | None = None) -> tuple[str, str]:
    """Copy incoming file to the user's sandbox, create doc+version, enqueue extract.

    Returns (document_id, version_id).
    Raises ValueError for unsupported file types or missing user context.
    """
    ext = Path(original_name).suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise ValueError(f"unsupported file type: {ext}")

    user_id = current_user_id.get()
    if not user_id:
        raise ValueError("missing user context; cannot sandbox upload")

    sandbox = Path(get_user_upload_dir()) / "standards"
    sandbox.mkdir(parents=True, exist_ok=True)
    stable_name = f"{uuid.uuid4().hex}{ext}"
    dest = sandbox / stable_name
    shutil.copyfile(file_path, dest)

    doc_code = Path(original_name).stem[:200]

    doc_id = repository.create_document(
        doc_code=doc_code, title=Path(original_name).stem,
        source_type=source_type, owner_user_id=user_id,
        raw_file_path=str(dest), source_url=source_url,
    )
    ver_id = repository.create_version(
        document_id=doc_id, version_label="v1.0", created_by=user_id,
    )
    repository.set_current_version(doc_id, ver_id)

    outbox.enqueue("extract_requested", {
        "document_id": doc_id, "version_id": ver_id,
        "file_path": str(dest), "ext": ext,
    })
    logger.info("ingested document_id=%s version_id=%s ext=%s", doc_id, ver_id, ext)
    return doc_id, ver_id
```

- [ ] **Step 3: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_uploader.py -v
git add data_agent/standards_platform/ingestion/__init__.py data_agent/standards_platform/ingestion/uploader.py data_agent/standards_platform/tests/test_uploader.py
git commit -m "feat(std-platform): uploader — sandbox + doc/version creation + enqueue extract"
```

## Task 12: Classifier — LLM-driven source_type + doc_code recognition

**Files:**
- Create: `data_agent/standards_platform/ingestion/classifier.py`
- Create: `data_agent/standards_platform/tests/test_classifier.py`

- [ ] **Step 1: Failing test**

Create `data_agent/standards_platform/tests/test_classifier.py`:
```python
from unittest.mock import patch, MagicMock
from data_agent.standards_platform.ingestion.classifier import classify


def _fake_llm(json_response: dict):
    fake = MagicMock()
    fake.generate.return_value = MagicMock(text=__import__("json").dumps(json_response))
    return fake


def test_recognises_national_gb():
    with patch("data_agent.standards_platform.ingestion.classifier.create_model",
               return_value=_fake_llm({"source_type": "national",
                                       "doc_code": "GB/T 13923-2022", "confidence": 0.93})):
        out = classify(filename="GB-T-13923-2022.docx",
                       text_excerpt="基础地理信息要素分类与代码")
    assert out["source_type"] == "national"
    assert out["doc_code"].startswith("GB/T 13923")


def test_recognises_industry_ch():
    with patch("data_agent.standards_platform.ingestion.classifier.create_model",
               return_value=_fake_llm({"source_type": "industry",
                                       "doc_code": "CH/T 9011-2018", "confidence": 0.9})):
        out = classify(filename="CH-T-9011-2018.docx", text_excerpt="基础地理信息数字成果...")
    assert out["source_type"] == "industry"


def test_falls_back_to_enterprise_when_unrecognised():
    with patch("data_agent.standards_platform.ingestion.classifier.create_model",
               return_value=_fake_llm({"source_type": "enterprise",
                                       "doc_code": "SMP-DS-001", "confidence": 0.4})):
        out = classify(filename="internal-spec.docx", text_excerpt="本院数据规范...")
    assert out["source_type"] == "enterprise"


def test_handles_llm_failure_gracefully():
    fake = MagicMock(); fake.generate.side_effect = RuntimeError("upstream down")
    with patch("data_agent.standards_platform.ingestion.classifier.create_model",
               return_value=fake):
        out = classify(filename="x.docx", text_excerpt="...")
    assert out["source_type"] == "draft"  # safe fallback
    assert out["confidence"] == 0.0
```

- [ ] **Step 2: Implement classifier**

Create `data_agent/standards_platform/ingestion/classifier.py`:
```python
"""LLM-based source_type + doc_code classification."""
from __future__ import annotations

import json
import re
from typing import Optional

from ...model_gateway import create_model
from ...observability import get_logger

logger = get_logger("standards_platform.ingestion.classifier")

_PROMPT = """你是数据标准元数据抽取助手。给定标准文档的文件名与开头片段，
返回严格 JSON：{{"source_type": one of [national,industry,enterprise,international,draft],
"doc_code": "...", "confidence": 0..1}}。
- national 例：GB / GB/T  - industry 例：CJ / CH / TD / SL
- international 例：ISO / IEC / OGC  - enterprise 例：内部编号
- 不能识别时 source_type=draft，doc_code 用文件名 stem。
filename: {filename}
excerpt: {excerpt}
"""


def classify(*, filename: str, text_excerpt: str,
             model_name: str = "gemini-2.5-flash") -> dict:
    excerpt = text_excerpt[:1500]
    try:
        model = create_model(model_name)
        rsp = model.generate(_PROMPT.format(filename=filename, excerpt=excerpt))
        raw = getattr(rsp, "text", "") or str(rsp)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise ValueError("no JSON in LLM response")
        data = json.loads(m.group(0))
        return {
            "source_type": data.get("source_type", "draft"),
            "doc_code": data.get("doc_code") or filename.rsplit(".", 1)[0],
            "confidence": float(data.get("confidence", 0.0)),
        }
    except Exception as e:
        logger.warning("classify failed: %s", e)
        return {"source_type": "draft",
                "doc_code": filename.rsplit(".", 1)[0],
                "confidence": 0.0}
```

- [ ] **Step 3: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_classifier.py -v
git add data_agent/standards_platform/ingestion/classifier.py data_agent/standards_platform/tests/test_classifier.py
git commit -m "feat(std-platform): LLM-based source-type/doc-code classifier"
```

## Task 13: Web fetcher — allowlist + SSRF guard + manual-paste fallback

**Files:**
- Create: `data_agent/standards_platform/ingestion/web_fetcher.py`
- Create: `data_agent/standards_platform/tests/test_web_fetcher.py`

- [ ] **Step 1: Failing test**

Create `data_agent/standards_platform/tests/test_web_fetcher.py`:
```python
import pytest
from unittest.mock import patch, MagicMock

from data_agent.standards_platform.ingestion import web_fetcher as wf


def test_rejects_url_outside_allowlist():
    with pytest.raises(wf.NotAllowed):
        wf.fetch("https://evil.example.com/spec.pdf")


@pytest.mark.parametrize("ip_url", [
    "http://10.0.0.1/x", "http://192.168.1.1/x",
    "http://172.16.5.5/x", "http://127.0.0.1/x", "http://169.254.1.1/x",
])
def test_rejects_ssrf_targets(ip_url):
    with pytest.raises(wf.NotAllowed):
        wf.fetch(ip_url)


def test_respects_robots_disallow():
    fake_resp = MagicMock(status_code=200, text="User-agent: *\nDisallow: /\n",
                          headers={"content-type": "text/plain"})
    with patch("data_agent.standards_platform.ingestion.web_fetcher.requests.get",
               return_value=fake_resp):
        with pytest.raises(wf.NotAllowed, match="robots"):
            wf.fetch("https://arxiv.org/abs/2401.00001")


def test_truncates_when_over_max_bytes():
    big = b"a" * (20 * 1024 * 1024)
    robots = MagicMock(status_code=200, text="User-agent: *\nAllow: /\n",
                       headers={"content-type":"text/plain"})
    page = MagicMock(status_code=200, content=big,
                     headers={"content-type": "text/html"})
    page.iter_content = lambda chunk_size: [big[:chunk_size]]
    with patch("data_agent.standards_platform.ingestion.web_fetcher.requests.get",
               side_effect=[robots, page]):
        out = wf.fetch("https://arxiv.org/abs/2401.00002", max_bytes=1024)
    assert len(out["body"]) <= 1024
    assert out["truncated"] is True


def test_manual_paste_persists_snapshot():
    snap_id = wf.save_manual("https://std.samr.gov.cn/abc",
                              pasted_text="完整正文……", user_id="alice")
    assert isinstance(snap_id, str) and len(snap_id) > 0
```

- [ ] **Step 2: Implement web fetcher**

Create `data_agent/standards_platform/ingestion/web_fetcher.py`:
```python
"""HTTP fetcher with allowlist, SSRF guard, robots.txt, size cap, manual paste."""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.robotparser
import uuid
from pathlib import Path

import requests
from sqlalchemy import text

from ...db_engine import get_engine
from ...observability import get_logger
from ...user_context import get_user_upload_dir
from .. import config as cfg_mod

logger = get_logger("standards_platform.ingestion.web_fetcher")


class NotAllowed(Exception):
    """Raised when a URL is rejected by allowlist, SSRF guard, or robots."""


_PRIVATE_NETS = [ipaddress.ip_network(n) for n in
    ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
     "127.0.0.0/8", "169.254.0.0/16", "::1/128", "fc00::/7")]


def _is_private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if any(addr in net for net in _PRIVATE_NETS):
            return True
    return False


def _check_allowed(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    cfg = cfg_mod.StandardsConfig.from_env()
    if host not in cfg.web_domains_allowlist:
        raise NotAllowed(f"host not in allowlist: {host}")
    if _is_private(host):
        raise NotAllowed(f"refusing private/loopback target: {host}")
    return host
```
(continued)

- [ ] **Step 3: Append fetch + save_manual**

Append to `web_fetcher.py`:
```python
def fetch(url: str, *, user_agent: str = "GIS-Data-Agent-Standards/0.1",
          max_bytes: int = 10 * 1024 * 1024, timeout: int = 30) -> dict:
    host = _check_allowed(url)
    robots_url = f"https://{host}/robots.txt"
    try:
        rb = requests.get(robots_url, headers={"User-Agent": user_agent}, timeout=10)
        rp = urllib.robotparser.RobotFileParser(); rp.parse(rb.text.splitlines())
        if not rp.can_fetch(user_agent, url):
            raise NotAllowed(f"blocked by robots.txt: {url}")
    except requests.RequestException:
        logger.warning("robots.txt unreachable for %s — proceeding", host)

    rsp = requests.get(url, headers={"User-Agent": user_agent},
                       timeout=timeout, stream=True)
    chunks, size, truncated = [], 0, False
    for chunk in rsp.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        if size + len(chunk) > max_bytes:
            chunks.append(chunk[: max_bytes - size]); truncated = True; break
        chunks.append(chunk); size += len(chunk)
    body = b"".join(chunks)
    return {
        "url": url, "status": rsp.status_code,
        "headers": dict(rsp.headers), "body": body, "truncated": truncated,
    }


def save_manual(url: str, *, pasted_text: str, user_id: str) -> str:
    """Manual-paste fallback when the source rejects automated fetch."""
    sandbox = Path(get_user_upload_dir()) / "standards" / "snapshots"
    sandbox.mkdir(parents=True, exist_ok=True)
    snap_id = str(uuid.uuid4())
    txt_path = sandbox / f"{snap_id}.txt"
    txt_path.write_text(pasted_text, encoding="utf-8")
    eng = get_engine()
    with eng.connect() as conn:
        conn.execute(text("""
            INSERT INTO std_web_snapshot (id, url, http_status, html_path, extracted_text)
            VALUES (:i, :u, 0, :p, :t)
        """), {"i": snap_id, "u": url, "p": str(txt_path), "t": pasted_text[:200000]})
        conn.commit()
    return snap_id
```

- [ ] **Step 4: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_web_fetcher.py -v
git add data_agent/standards_platform/ingestion/web_fetcher.py data_agent/standards_platform/tests/test_web_fetcher.py
git commit -m "feat(std-platform): web fetcher (allowlist + SSRF + robots + manual paste)"
```

## Task 14: Extractor runner — dispatch to docx_extractor or xmi_parser

**Files:**
- Create: `data_agent/standards_platform/ingestion/extractor_runner.py`
- Create: `data_agent/standards_platform/tests/test_extractor_runner.py`

- [ ] **Step 1: Failing test**

```python
# data_agent/standards_platform/tests/test_extractor_runner.py
from unittest.mock import patch, MagicMock
from data_agent.standards_platform.ingestion.extractor_runner import run_extractor


def test_dispatches_to_docx_extractor(tmp_path):
    f = tmp_path / "x.docx"; f.write_bytes(b"PK")
    with patch("data_agent.standards_platform.ingestion.extractor_runner.docx_extract",
               return_value={"FieldTable": [{"name": "n"}], "LayerTable": []}) as fake:
        out = run_extractor(str(f))
    fake.assert_called_once()
    assert "FieldTable" in out


def test_dispatches_to_xmi_parser(tmp_path):
    f = tmp_path / "m.xmi"; f.write_text("<XMI/>", encoding="utf-8")
    with patch("data_agent.standards_platform.ingestion.extractor_runner.parse_xmi_file",
               return_value=MagicMock(modules=[], classes=[])) as fake:
        out = run_extractor(str(f))
    fake.assert_called_once()
    assert "modules" in out


def test_unknown_ext_raises(tmp_path):
    f = tmp_path / "x.csv"; f.write_text("a,b")
    import pytest
    with pytest.raises(ValueError, match="unsupported"):
        run_extractor(str(f))
```

- [ ] **Step 2: Implement**

```python
# data_agent/standards_platform/ingestion/extractor_runner.py
"""Dispatches incoming files to the right parser. Returns a normalised dict."""
from __future__ import annotations

from pathlib import Path

from ...standards.docx_extractor import extract as docx_extract
from ...standards.xmi_parser import parse_xmi_file
from ...observability import get_logger

logger = get_logger("standards_platform.ingestion.extractor_runner")


def run_extractor(file_path: str, *, module_name: str | None = None) -> dict:
    ext = Path(file_path).suffix.lower()
    if ext == ".docx":
        return docx_extract(file_path, module_name or Path(file_path).stem)
    if ext == ".xmi":
        result = parse_xmi_file(file_path)
        return {"modules": getattr(result, "modules", []),
                "classes": getattr(result, "classes", []),
                "associations": getattr(result, "associations", [])}
    raise ValueError(f"unsupported extension: {ext}")
```

- [ ] **Step 3: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_extractor_runner.py -v
git add data_agent/standards_platform/ingestion/extractor_runner.py data_agent/standards_platform/tests/test_extractor_runner.py
git commit -m "feat(std-platform): extractor runner — docx/xmi dispatch"
```

## Task 15: Structurer — extractor output → clause tree + terms + data elements + value domains

**Files:**
- Create: `data_agent/standards_platform/analysis/__init__.py` (empty)
- Create: `data_agent/standards_platform/analysis/structurer.py`
- Create: `data_agent/standards_platform/tests/test_structurer.py`

- [ ] **Step 1: Failing test**

```python
# data_agent/standards_platform/tests/test_structurer.py
import uuid, pytest
from sqlalchemy import text
from data_agent.db_engine import get_engine
from data_agent.standards_platform import repository as repo
from data_agent.standards_platform.analysis.structurer import structure_extracted
from data_agent.user_context import current_user_id


@pytest.fixture
def doc_and_version():
    eng = get_engine()
    if eng is None: pytest.skip("DB unavailable")
    current_user_id.set("u_test")
    code = f"TEST-{uuid.uuid4().hex[:6]}"
    doc_id = repo.create_document(doc_code=code, title="t",
        source_type="enterprise", owner_user_id="u_test", raw_file_path="/tmp/x")
    ver_id = repo.create_version(document_id=doc_id, version_label="v1.0",
                                  created_by="u_test")
    repo.set_current_version(doc_id, ver_id)
    yield doc_id, ver_id
    with eng.connect() as c:
        c.execute(text("DELETE FROM std_document WHERE id=:i"), {"i": doc_id}); c.commit()


def test_extractor_dict_to_clause_tree(doc_and_version):
    doc_id, ver_id = doc_and_version
    payload = {
        "FieldTable": [
            {"clause_no": "5.2", "heading": "建设用地", "kind": "section",
             "body_md": "建设用地分类与代码", "page": 12, "char_span": [0, 120]},
            {"clause_no": "5.2.1", "heading": "城市建设用地", "kind": "clause",
             "body_md": "城市建设用地的定义……", "page": 12, "char_span": [121, 320],
             "data_elements": [
                {"code": "URB_LAND_CODE", "name_zh": "城市用地代码",
                 "datatype": "varchar(8)", "obligation": "mandatory"}
             ],
             "terms": [{"term_code": "URB_LAND", "name_zh": "城市建设用地",
                        "definition": "..."}]
            },
        ],
        "LayerTable": [],
    }
    out = structure_extracted(doc_id=doc_id, version_id=ver_id, payload=payload)
    assert out["clauses_inserted"] >= 2
    assert out["data_elements_inserted"] >= 1
    assert out["terms_inserted"] >= 1
```

- [ ] **Step 2: Implement**

```python
# data_agent/standards_platform/analysis/__init__.py — empty.

# data_agent/standards_platform/analysis/structurer.py
"""Take docx_extractor or xmi_parser output and write to std_clause /
std_term / std_data_element / std_value_domain. Idempotent (UPSERT by
(document_version_id, ordinal_path/code)).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from ...db_engine import get_engine
from ...observability import get_logger

logger = get_logger("standards_platform.analysis.structurer")


def _ordinal_to_ltree(clause_no: str) -> str:
    cleaned = clause_no.strip().replace(" ", "")
    if not cleaned:
        return "0"
    return cleaned.replace(".", ".")  # already dotted; ltree accepts


def structure_extracted(*, doc_id: str, version_id: str,
                        payload: dict) -> dict[str, int]:
    counts = {"clauses_inserted": 0, "data_elements_inserted": 0,
              "terms_inserted": 0, "value_domains_inserted": 0}
    eng = get_engine()
    if eng is None:
        return counts

    field_rows = payload.get("FieldTable", []) or []
    with eng.begin() as conn:
        clause_id_by_no: dict[str, str] = {}

        for row in field_rows:
            clause_no = str(row.get("clause_no") or row.get("ordinal") or "0")
            ord_path = _ordinal_to_ltree(clause_no)
            cid = str(uuid.uuid4())
            origin = {"page": row.get("page"), "char_span": row.get("char_span")}
            conn.execute(text("""
                INSERT INTO std_clause (id, document_id, document_version_id,
                    ordinal_path, heading, clause_no, kind, body_md, source_origin)
                VALUES (:i, :d, :v, :p::ltree, :h, :n, :k, :b, CAST(:o AS jsonb))
                ON CONFLICT (document_version_id, ordinal_path) DO UPDATE
                  SET heading=EXCLUDED.heading, body_md=EXCLUDED.body_md,
                      kind=EXCLUDED.kind, updated_at=now()
                RETURNING id
            """), {"i": cid, "d": doc_id, "v": version_id, "p": ord_path,
                    "h": row.get("heading", ""), "n": clause_no,
                    "k": row.get("kind", "clause"),
                    "b": row.get("body_md", ""),
                    "o": json.dumps(origin, ensure_ascii=False)})
            clause_id_by_no[clause_no] = cid
            counts["clauses_inserted"] += 1
            for de in row.get("data_elements", []) or []:
                conn.execute(text("""
                    INSERT INTO std_data_element (document_version_id, code,
                        name_zh, name_en, definition, datatype, obligation,
                        defined_by_clause_id)
                    VALUES (:v, :c, :z, :e, :df, :dt, :ob, :cl)
                    ON CONFLICT (document_version_id, code) DO UPDATE
                      SET name_zh=EXCLUDED.name_zh, datatype=EXCLUDED.datatype
                """), {"v": version_id, "c": de["code"],
                        "z": de.get("name_zh"), "e": de.get("name_en"),
                        "df": de.get("definition"),
                        "dt": de.get("datatype"),
                        "ob": de.get("obligation", "optional"),
                        "cl": cid})
                counts["data_elements_inserted"] += 1
            for trm in row.get("terms", []) or []:
                conn.execute(text("""
                    INSERT INTO std_term (document_version_id, term_code,
                        name_zh, name_en, definition, defined_by_clause_id)
                    VALUES (:v, :tc, :z, :e, :df, :cl)
                    ON CONFLICT (document_version_id, term_code) DO UPDATE
                      SET name_zh=EXCLUDED.name_zh
                """), {"v": version_id, "tc": trm["term_code"],
                        "z": trm.get("name_zh"), "e": trm.get("name_en"),
                        "df": trm.get("definition"), "cl": cid})
                counts["terms_inserted"] += 1
    return counts
```

- [ ] **Step 3: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_structurer.py -v
git add data_agent/standards_platform/analysis/__init__.py data_agent/standards_platform/analysis/structurer.py data_agent/standards_platform/tests/test_structurer.py
git commit -m "feat(std-platform): structurer — clause tree + data elements + terms"
```

## Task 16: Embedder — batch-embed clauses, terms, data elements

**Files:**
- Create: `data_agent/standards_platform/analysis/embedder.py`
- Create: `data_agent/standards_platform/tests/test_embedder.py`

- [ ] **Step 1: Failing test**

```python
# data_agent/standards_platform/tests/test_embedder.py
from unittest.mock import patch
import pytest
from sqlalchemy import text
from data_agent.db_engine import get_engine
from data_agent.standards_platform.analysis.embedder import embed_version


def test_embed_writes_vectors_for_all_three_entities():
    eng = get_engine()
    if eng is None: pytest.skip("DB unavailable")
    # seed a version with 1 clause + 1 data_element + 1 term
    import uuid
    ver_id = str(uuid.uuid4()); doc_id = str(uuid.uuid4())
    with eng.connect() as c:
        c.execute(text("INSERT INTO std_document (id, doc_code, title, source_type, "
                       "owner_user_id) VALUES (:i, :c, 't', 'draft', 'u')"),
                  {"i": doc_id, "c": f"T-{uuid.uuid4().hex[:6]}"})
        c.execute(text("INSERT INTO std_document_version (id, document_id, version_label, "
                       "semver_major) VALUES (:i, :d, 'v1.0', 1)"),
                  {"i": ver_id, "d": doc_id})
        c.execute(text("INSERT INTO std_clause (id, document_id, document_version_id, "
                       "ordinal_path, kind, body_md) VALUES (:i, :d, :v, '5.2'::ltree, "
                       "'clause', 'some body text')"),
                  {"i": str(uuid.uuid4()), "d": doc_id, "v": ver_id})
        c.execute(text("INSERT INTO std_data_element (document_version_id, code, "
                       "name_zh, definition) VALUES (:v, 'X', 'x', 'x def')"), {"v": ver_id})
        c.execute(text("INSERT INTO std_term (document_version_id, term_code, name_zh) "
                       "VALUES (:v, 'T1', 't1')"), {"v": ver_id})
        c.commit()

    fake = [[0.1] * 768] * 3
    with patch("data_agent.standards_platform.analysis.embedder.get_embeddings",
               return_value=fake), \
         patch("data_agent.standards_platform.analysis.embedder.get_active_dimension",
               return_value=768):
        report = embed_version(version_id=ver_id)

    assert report["clauses_embedded"] >= 1
    assert report["data_elements_embedded"] >= 1
    assert report["terms_embedded"] >= 1

    with eng.connect() as c:
        row = c.execute(text("SELECT embedding IS NOT NULL AS has FROM std_clause "
                             "WHERE document_version_id=:v"), {"v": ver_id}).first()
        assert row.has


def test_embed_graceful_on_gateway_failure():
    import uuid
    with patch("data_agent.standards_platform.analysis.embedder.get_embeddings",
               return_value=[]):
        report = embed_version(version_id=str(uuid.uuid4()))
    assert report["clauses_embedded"] == 0
```

- [ ] **Step 2: Implement**

```python
# data_agent/standards_platform/analysis/embedder.py
"""Batch-compute embeddings via embedding_gateway; write to vector columns.
Dimension must match get_active_dimension() (default 768). Empty on failure."""
from __future__ import annotations

from sqlalchemy import text

from ...db_engine import get_engine
from ...embedding_gateway import get_embeddings, get_active_dimension
from ...observability import get_logger

logger = get_logger("standards_platform.analysis.embedder")


def _format_vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def _embed_table(*, version_id: str, table: str, id_col: str,
                 text_expr: str) -> int:
    eng = get_engine()
    if eng is None:
        return 0
    with eng.connect() as conn:
        rows = conn.execute(text(
            f"SELECT {id_col} AS id, {text_expr} AS body FROM {table} "
            f"WHERE document_version_id = :v AND embedding IS NULL"
        ), {"v": version_id}).mappings().all()
    if not rows:
        return 0
    texts = [r["body"] or "" for r in rows]
    vecs = get_embeddings(texts)
    if len(vecs) != len(texts):
        logger.warning("embedding count mismatch (%d vs %d) — skipping %s",
                       len(vecs), len(texts), table)
        return 0
    dim = get_active_dimension()
    ok = 0
    with eng.begin() as conn:
        for r, v in zip(rows, vecs):
            if len(v) != dim:
                continue
            conn.execute(text(
                f"UPDATE {table} SET embedding = :e::vector WHERE {id_col} = :i"
            ), {"e": _format_vec(v), "i": r["id"]})
            ok += 1
    return ok


def embed_version(*, version_id: str) -> dict[str, int]:
    return {
        "clauses_embedded": _embed_table(version_id=version_id,
            table="std_clause", id_col="id",
            text_expr="COALESCE(heading,'') || ' ' || COALESCE(body_md,'')"),
        "terms_embedded": _embed_table(version_id=version_id,
            table="std_term", id_col="id",
            text_expr="COALESCE(name_zh,'') || ' ' || COALESCE(definition,'')"),
        "data_elements_embedded": _embed_table(version_id=version_id,
            table="std_data_element", id_col="id",
            text_expr="COALESCE(name_zh,'') || ' ' || COALESCE(definition,'')"),
    }
```

- [ ] **Step 3: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_embedder.py -v
git add data_agent/standards_platform/analysis/embedder.py data_agent/standards_platform/tests/test_embedder.py
git commit -m "feat(std-platform): embedder — pgvector writes for clauses/terms/DEs"
```

## Task 17: Deduper — pgvector-based similar-clause lookup

**Files:**
- Create: `data_agent/standards_platform/analysis/deduper.py`
- Create: `data_agent/standards_platform/tests/test_deduper.py`

- [ ] **Step 1: Failing test**

```python
# data_agent/standards_platform/tests/test_deduper.py
import uuid, pytest
from sqlalchemy import text
from data_agent.db_engine import get_engine
from data_agent.standards_platform.analysis.deduper import find_similar_clauses


def _seed(c, doc_id, ver_id, body, vec):
    c.execute(text("""
      INSERT INTO std_clause (id, document_id, document_version_id, ordinal_path,
        kind, body_md, embedding)
      VALUES (:i, :d, :v, '5.2'::ltree, 'clause', :b, :e::vector)
    """), {"i": str(uuid.uuid4()), "d": doc_id, "v": ver_id,
            "b": body, "e": "[" + ",".join(str(x) for x in vec) + "]"})


def test_returns_nearest_neighbours_cross_version():
    eng = get_engine()
    if eng is None: pytest.skip("DB unavailable")
    doc_a, ver_a = str(uuid.uuid4()), str(uuid.uuid4())
    doc_b, ver_b = str(uuid.uuid4()), str(uuid.uuid4())
    with eng.begin() as c:
        for d,v in ((doc_a,ver_a),(doc_b,ver_b)):
            c.execute(text("INSERT INTO std_document (id, doc_code, title, source_type, "
                           "owner_user_id) VALUES (:i, :c, 't', 'draft', 'u')"),
                      {"i": d, "c": f"T-{uuid.uuid4().hex[:6]}"})
            c.execute(text("INSERT INTO std_document_version (id, document_id, version_label, "
                           "semver_major) VALUES (:i, :d, 'v1.0', 1)"), {"i": v, "d": d})
        _seed(c, doc_a, ver_a, "城市建设用地定义",
              [1.0] + [0.0] * 767)
        _seed(c, doc_b, ver_b, "城市建设用地定义 2",
              [0.99, 0.01] + [0.0] * 766)
    hits = find_similar_clauses(version_id=ver_a, top_k=5, min_similarity=0.5)
    assert any(h["document_version_id"] == ver_b for h in hits)
```

- [ ] **Step 2: Implement**

```python
# data_agent/standards_platform/analysis/deduper.py
"""Similar-clause lookup across versions via pgvector cosine similarity."""
from __future__ import annotations

from sqlalchemy import text
from ...db_engine import get_engine


def find_similar_clauses(*, version_id: str, top_k: int = 10,
                         min_similarity: float = 0.8) -> list[dict]:
    eng = get_engine()
    if eng is None:
        return []
    with eng.connect() as conn:
        rows = conn.execute(text("""
            WITH src AS (
              SELECT id, embedding FROM std_clause
              WHERE document_version_id = :v AND embedding IS NOT NULL
            )
            SELECT s.id AS source_clause_id, t.id AS target_clause_id,
                   t.document_version_id, t.body_md,
                   1 - (s.embedding <=> t.embedding) AS similarity
            FROM src s
            JOIN std_clause t ON t.document_version_id <> :v
                               AND t.embedding IS NOT NULL
            WHERE 1 - (s.embedding <=> t.embedding) >= :thr
            ORDER BY similarity DESC
            LIMIT :k
        """), {"v": version_id, "thr": min_similarity, "k": top_k}).mappings().all()
        return [dict(r) for r in rows]
```

- [ ] **Step 3: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_deduper.py -v
git add data_agent/standards_platform/analysis/deduper.py data_agent/standards_platform/tests/test_deduper.py
git commit -m "feat(std-platform): deduper — pgvector similar-clause lookup"
```

## Task 18: Handlers — dispatch table mapping event_type → handler

**Files:**
- Create: `data_agent/standards_platform/handlers.py`
- Create: `data_agent/standards_platform/tests/test_handlers.py`

- [ ] **Step 1: Failing test**

```python
# data_agent/standards_platform/tests/test_handlers.py
from unittest.mock import patch, MagicMock
import pytest
from data_agent.standards_platform.handlers import dispatch


def test_extract_requested_routes_to_extract_then_enqueues_structure():
    with patch("data_agent.standards_platform.handlers.run_extractor",
               return_value={"FieldTable":[]}) as fake_ex, \
         patch("data_agent.standards_platform.handlers.outbox.enqueue") as fake_enq:
        dispatch({"id":"e1","event_type":"extract_requested",
                  "payload":{"document_id":"D","version_id":"V",
                             "file_path":"/tmp/x.docx","ext":".docx"},
                  "attempts":0})
    fake_ex.assert_called_once()
    fake_enq.assert_called_with("structure_requested",
        {"document_id":"D","version_id":"V","extracted":{"FieldTable":[]}})


def test_structure_requested_routes_to_structurer_then_enqueues_embed():
    with patch("data_agent.standards_platform.handlers.structure_extracted",
               return_value={"clauses_inserted":3}) as fake_s, \
         patch("data_agent.standards_platform.handlers.outbox.enqueue") as fake_enq:
        dispatch({"id":"e2","event_type":"structure_requested",
                  "payload":{"document_id":"D","version_id":"V",
                             "extracted":{"FieldTable":[]}}, "attempts":0})
    fake_s.assert_called_once()
    fake_enq.assert_called_with("embed_requested", {"version_id":"V"})


def test_embed_requested_then_enqueues_dedupe():
    with patch("data_agent.standards_platform.handlers.embed_version",
               return_value={"clauses_embedded":3}), \
         patch("data_agent.standards_platform.handlers.outbox.enqueue") as fake_enq:
        dispatch({"id":"e3","event_type":"embed_requested",
                  "payload":{"version_id":"V"}, "attempts":0})
    fake_enq.assert_called_with("dedupe_requested", {"version_id":"V"})


def test_unknown_event_raises():
    with pytest.raises(ValueError):
        dispatch({"id":"x","event_type":"nope","payload":{}, "attempts":0})
```

- [ ] **Step 2: Implement**

```python
# data_agent/standards_platform/handlers.py
"""Event dispatch: event_type -> handler. Handlers chain subsequent events."""
from __future__ import annotations

from .ingestion.extractor_runner import run_extractor
from .analysis.structurer import structure_extracted
from .analysis.embedder import embed_version
from .analysis.deduper import find_similar_clauses
from .ingestion.web_fetcher import fetch as web_fetch, save_manual
from . import outbox, repository
from ..observability import get_logger

logger = get_logger("standards_platform.handlers")


def dispatch(event: dict) -> None:
    et = event["event_type"]; p = event["payload"]
    logger.info("dispatch %s (event_id=%s, attempts=%d)", et, event.get("id"),
                event.get("attempts", 0))
    if et == "extract_requested":
        extracted = run_extractor(p["file_path"])
        outbox.enqueue("structure_requested",
                       {"document_id": p["document_id"],
                        "version_id": p["version_id"],
                        "extracted": extracted})
    elif et == "structure_requested":
        structure_extracted(doc_id=p["document_id"], version_id=p["version_id"],
                            payload=p["extracted"])
        outbox.enqueue("embed_requested", {"version_id": p["version_id"]})
    elif et == "embed_requested":
        embed_version(version_id=p["version_id"])
        outbox.enqueue("dedupe_requested", {"version_id": p["version_id"]})
    elif et == "dedupe_requested":
        find_similar_clauses(version_id=p["version_id"])
        # Final step for P0: mark document as drafting.
        doc_id = p.get("document_id")
        if doc_id is None:
            eng = __import__("data_agent.db_engine", fromlist=["get_engine"]).get_engine()
            from sqlalchemy import text as _t
            with eng.connect() as c:
                row = c.execute(_t("SELECT document_id FROM std_document_version WHERE id = :v"),
                                {"v": p["version_id"]}).first()
                if row:
                    doc_id = row.document_id
        if doc_id:
            repository.update_document_status(doc_id, "drafting")
    elif et == "web_snapshot_requested":
        web_fetch(p["url"])
    else:
        raise ValueError(f"unknown event type: {et}")
```

- [ ] **Step 3: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_handlers.py -v
git add data_agent/standards_platform/handlers.py data_agent/standards_platform/tests/test_handlers.py
git commit -m "feat(std-platform): event dispatcher (extract→structure→embed→dedupe)"
```

## Task 19: Outbox worker — independent process entrypoint

**Files:**
- Create: `data_agent/standards_platform/outbox_worker.py`
- Create: `data_agent/standards_platform/tests/test_outbox_worker.py`

- [ ] **Step 1: Failing test**

```python
# data_agent/standards_platform/tests/test_outbox_worker.py
from unittest.mock import patch
import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine
from data_agent.standards_platform import outbox as ob
from data_agent.standards_platform.outbox_worker import run_once


@pytest.fixture
def clean_outbox():
    eng = get_engine()
    if eng is None: pytest.skip("DB unavailable")
    with eng.connect() as c:
        c.execute(text("DELETE FROM std_outbox")); c.commit()
    yield eng


def test_run_once_calls_dispatch_and_marks_done(clean_outbox):
    evt_id = ob.enqueue("embed_requested", {"version_id": "V"})
    with patch("data_agent.standards_platform.outbox_worker.dispatch") as fake:
        n = run_once(batch_size=5, max_attempts=5)
    assert n == 1
    fake.assert_called_once()
    with clean_outbox.connect() as c:
        status = c.execute(text("SELECT status FROM std_outbox WHERE id=:i"),
                           {"i": evt_id}).scalar()
    assert status == "done"


def test_run_once_marks_failed_after_max_attempts(clean_outbox):
    evt_id = ob.enqueue("embed_requested", {"version_id": "V"})
    with patch("data_agent.standards_platform.outbox_worker.dispatch",
               side_effect=RuntimeError("boom")):
        for _ in range(5):
            run_once(batch_size=5, max_attempts=5)
            # bump next_attempt_at back so the same event is picked again
            with clean_outbox.connect() as c:
                c.execute(text("UPDATE std_outbox SET next_attempt_at = now(), "
                               "status='pending' WHERE id=:i AND status='pending'"),
                          {"i": evt_id}); c.commit()
    with clean_outbox.connect() as c:
        status = c.execute(text("SELECT status FROM std_outbox WHERE id=:i"),
                           {"i": evt_id}).scalar()
    assert status == "failed"
```

- [ ] **Step 2: Implement**

```python
# data_agent/standards_platform/outbox_worker.py
"""Independent outbox worker process.

Entrypoint:
    python -m data_agent.standards_platform.outbox_worker
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from . import outbox
from .config import StandardsConfig
from .handlers import dispatch
from ..observability import get_logger

logger = get_logger("standards_platform.outbox_worker")

_shutdown = False


def _handle_signal(sig, frame):
    global _shutdown
    _shutdown = True
    logger.info("received signal %s — draining and shutting down", sig)


def run_once(*, batch_size: int, max_attempts: int) -> int:
    events = outbox.claim_batch(limit=batch_size)
    for evt in events:
        try:
            dispatch(evt)
            outbox.complete(evt["id"])
        except Exception as e:  # keep worker up on handler errors
            logger.exception("handler failed for event %s: %s", evt.get("id"), e)
            outbox.fail(evt["id"], str(e), max_attempts=max_attempts)
    return len(events)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Standards Platform outbox worker (independent process).")
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--once", action="store_true",
                    help="process a single batch and exit (for CI).")
    args = ap.parse_args(argv)

    cfg = StandardsConfig.from_env()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    logger.info("outbox_worker starting (interval=%ss, max_attempts=%d)",
                cfg.outbox_worker_interval_sec, cfg.outbox_max_attempts)

    if args.once:
        run_once(batch_size=args.batch_size, max_attempts=cfg.outbox_max_attempts)
        return 0

    while not _shutdown:
        run_once(batch_size=args.batch_size, max_attempts=cfg.outbox_max_attempts)
        for _ in range(cfg.outbox_worker_interval_sec):
            if _shutdown: break
            time.sleep(1)
    logger.info("outbox_worker exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_outbox_worker.py -v
git add data_agent/standards_platform/outbox_worker.py data_agent/standards_platform/tests/test_outbox_worker.py
git commit -m "feat(std-platform): outbox_worker entrypoint (independent process)"
```

## Task 20: REST routes — `/api/std/*` (12 endpoints) + mount

**Files:**
- Create: `data_agent/api/standards_routes.py`
- Modify: `data_agent/frontend_api.py` (mount the routes)
- Create: `data_agent/standards_platform/tests/test_api_standards.py`

P0 endpoints (each: auth + RBAC + happy + 1 error):

| Method | Path | Description |
|---|---|---|
| GET | `/api/std/documents` | list (filter: owner, status, source_type) |
| POST | `/api/std/documents` | upload (multipart: file, source_type, source_url?) |
| GET | `/api/std/documents/{doc_id}` | detail (with current_version) |
| GET | `/api/std/documents/{doc_id}/versions` | version list |
| GET | `/api/std/versions/{version_id}/clauses` | clause tree |
| GET | `/api/std/versions/{version_id}/data-elements` | data element list |
| GET | `/api/std/versions/{version_id}/terms` | term list |
| GET | `/api/std/versions/{version_id}/value-domains` | value domain list |
| GET | `/api/std/versions/{version_id}/similar` | dedupe hits (P0 = read-only view of analysis result) |
| POST | `/api/std/web/fetch` | fetch URL into snapshot (allowlist enforced) |
| POST | `/api/std/web/manual` | manual paste fallback |
| GET | `/api/std/outbox/status` | counts by status (admin only) |

- [ ] **Step 1: Failing test (representative subset)**

```python
# data_agent/standards_platform/tests/test_api_standards.py
import io, pytest
from unittest.mock import patch
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.frontend_api import mount_frontend_api


def _client():
    app = Starlette()
    mount_frontend_api(app)
    return TestClient(app, raise_server_exceptions=False)


def _auth_user(monkeypatch, username="alice", role="standard_editor"):
    class U: pass
    u = U(); u.identifier = username; u.metadata = {"role": role}
    monkeypatch.setattr("data_agent.api.helpers._get_user_from_request", lambda r: u)


def test_list_documents_requires_auth(monkeypatch):
    monkeypatch.setattr("data_agent.api.helpers._get_user_from_request", lambda r: None)
    r = _client().get("/api/std/documents")
    assert r.status_code == 401


def test_upload_creates_document(monkeypatch):
    _auth_user(monkeypatch)
    with patch("data_agent.api.standards_routes.ingest_upload",
               return_value=("d1", "v1")):
        files = {"file": ("g.docx", io.BytesIO(b"PK"), "application/octet-stream")}
        r = _client().post("/api/std/documents", files=files,
                            data={"source_type": "national"})
    assert r.status_code == 200
    assert r.json()["document_id"] == "d1"


def test_viewer_cannot_upload(monkeypatch):
    _auth_user(monkeypatch, role="viewer")
    files = {"file": ("g.docx", io.BytesIO(b"PK"), "application/octet-stream")}
    r = _client().post("/api/std/documents", files=files,
                        data={"source_type": "national"})
    assert r.status_code == 403


def test_outbox_status_admin_only(monkeypatch):
    _auth_user(monkeypatch, role="standard_editor")
    r = _client().get("/api/std/outbox/status")
    assert r.status_code == 403
    _auth_user(monkeypatch, role="admin")
    r = _client().get("/api/std/outbox/status")
    assert r.status_code == 200
```

- [ ] **Step 2: Implement routes module**

Create `data_agent/api/standards_routes.py`:
```python
"""Standards Platform REST routes (P0). Auth via _get_user_from_request +
_set_user_context, role gates inline."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..db_engine import get_engine
from ..observability import get_logger
from ..standards_platform import repository, outbox
from ..standards_platform.ingestion.uploader import ingest_upload
from ..standards_platform.ingestion.web_fetcher import fetch as web_fetch, save_manual, NotAllowed
from ..standards_platform.analysis.deduper import find_similar_clauses
from .helpers import _get_user_from_request, _set_user_context, _require_admin

logger = get_logger("api.standards_routes")

_EDITOR_ROLES = {"admin", "analyst", "standard_editor"}
_REVIEWER_ROLES = {"admin", "analyst", "standard_editor", "standard_reviewer"}


def _auth_or_401(request: Request):
    u = _get_user_from_request(request)
    if not u:
        return None, None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(u)
    return username, role, None


async def list_documents(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    owner = request.query_params.get("owner")
    status = request.query_params.get("status")
    rows = repository.list_documents(owner_user_id=owner, status=status)
    return JSONResponse({"documents": [
        {"id": str(r["id"]), "doc_code": r["doc_code"], "title": r["title"],
         "source_type": r["source_type"], "status": r["status"],
         "owner_user_id": r["owner_user_id"]} for r in rows]})


async def upload_document(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    if role not in _EDITOR_ROLES:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return JSONResponse({"error": "missing file"}, status_code=400)
    src_type = form.get("source_type", "enterprise")
    src_url = form.get("source_url") or None
    suffix = Path(upload.filename or "").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(upload.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        doc_id, ver_id = ingest_upload(tmp_path, original_name=upload.filename,
                                        source_type=src_type, source_url=src_url)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"document_id": doc_id, "version_id": ver_id})


async def get_document(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    doc_id = request.path_params["doc_id"]
    doc = repository.get_document(doc_id)
    if not doc:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"document": {k: (str(v) if hasattr(v, "hex") else v)
                                       for k, v in doc.items()}})
```
(continued)

- [ ] **Step 3: Append remaining endpoints**

Append to `data_agent/api/standards_routes.py`:
```python
async def list_versions(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, version_label, status, released_at FROM std_document_version "
            "WHERE document_id = :d ORDER BY semver_major DESC, semver_minor DESC, semver_patch DESC"
        ), {"d": request.path_params["doc_id"]}).mappings().all()
    return JSONResponse({"versions": [
        {"id": str(r["id"]), "version_label": r["version_label"],
         "status": r["status"],
         "released_at": r["released_at"].isoformat() if r["released_at"] else None}
        for r in rows]})


def _list_under_version(table: str, request: Request):
    """Generic helper for clauses / data-elements / terms / value-domains."""
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            f"SELECT * FROM {table} WHERE document_version_id = :v ORDER BY 1"
        ), {"v": request.path_params["version_id"]}).mappings().all()
    return [{k: (str(v) if hasattr(v, "hex") else v) for k, v in dict(r).items()
             if k != "embedding"} for r in rows]


async def list_clauses(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    return JSONResponse({"clauses": _list_under_version("std_clause", request)})


async def list_data_elements(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    return JSONResponse({"data_elements":
        _list_under_version("std_data_element", request)})


async def list_terms(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    return JSONResponse({"terms": _list_under_version("std_term", request)})


async def list_value_domains(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    return JSONResponse({"value_domains":
        _list_under_version("std_value_domain", request)})


async def list_similar(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    hits = find_similar_clauses(version_id=request.path_params["version_id"],
                                top_k=20, min_similarity=0.7)
    return JSONResponse({"hits": [{**h, "source_clause_id": str(h["source_clause_id"]),
                                    "target_clause_id": str(h["target_clause_id"]),
                                    "document_version_id": str(h["document_version_id"]),
                                    "similarity": float(h["similarity"])} for h in hits]})


async def web_fetch_route(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    if role not in _EDITOR_ROLES:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    body = await request.json()
    try:
        out = web_fetch(body["url"])
    except NotAllowed as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"status": out["status"], "truncated": out["truncated"],
                          "size": len(out["body"])})


async def web_manual_route(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    if role not in _EDITOR_ROLES:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    body = await request.json()
    snap = save_manual(body["url"], pasted_text=body["text"], user_id=username)
    return JSONResponse({"snapshot_id": snap})


async def outbox_status(request: Request):
    user, username, role, err = _require_admin(request)
    if err: return err
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT status, COUNT(*) AS n FROM std_outbox GROUP BY status"
        )).mappings().all()
    return JSONResponse({"counts": {r["status"]: r["n"] for r in rows}})


standards_routes = [
    Route("/api/std/documents", endpoint=list_documents, methods=["GET"]),
    Route("/api/std/documents", endpoint=upload_document, methods=["POST"]),
    Route("/api/std/documents/{doc_id}", endpoint=get_document, methods=["GET"]),
    Route("/api/std/documents/{doc_id}/versions", endpoint=list_versions, methods=["GET"]),
    Route("/api/std/versions/{version_id}/clauses", endpoint=list_clauses, methods=["GET"]),
    Route("/api/std/versions/{version_id}/data-elements", endpoint=list_data_elements, methods=["GET"]),
    Route("/api/std/versions/{version_id}/terms", endpoint=list_terms, methods=["GET"]),
    Route("/api/std/versions/{version_id}/value-domains", endpoint=list_value_domains, methods=["GET"]),
    Route("/api/std/versions/{version_id}/similar", endpoint=list_similar, methods=["GET"]),
    Route("/api/std/web/fetch", endpoint=web_fetch_route, methods=["POST"]),
    Route("/api/std/web/manual", endpoint=web_manual_route, methods=["POST"]),
    Route("/api/std/outbox/status", endpoint=outbox_status, methods=["GET"]),
]
```

- [ ] **Step 4: Mount routes in `frontend_api.py`**

Open `data_agent/frontend_api.py`. The function `get_frontend_api_routes()`
(around line 3777) imports a `get_X_routes()` from each submodule and splats
those lists into its returned list literal. Match that convention exactly —
do **not** import the bare `standards_routes` list.

First, change `data_agent/api/standards_routes.py` to also expose a helper:
append to that file:
```python
def get_standards_routes():
    return standards_routes
```

Then in `frontend_api.py::get_frontend_api_routes()`:
- Add near the other imports:
  ```python
  from .api.standards_routes import get_standards_routes
  ```
- In the returned list literal (starts around line 3805, closes with `]` near
  line 3960), add new `Route(...)` entries by splatting the list — just before
  the closing `]`:
  ```python
          *get_standards_routes(),
  ```
  (A trailing comma is fine; Starlette route order tolerates this position
  because all `/api/std/*` paths are specific and don't collide with other
  routes.)

- [ ] **Step 5: Run + commit**

```
.venv/Scripts/python.exe -m pytest data_agent/standards_platform/tests/test_api_standards.py -v
git add data_agent/api/standards_routes.py data_agent/frontend_api.py data_agent/standards_platform/tests/test_api_standards.py
git commit -m "feat(std-platform): /api/std/* P0 endpoints (12 routes)"
```

## Task 21: Frontend — StandardsTab + IngestSubTab + AnalyzeSubTab

**Files:**
- Create: `frontend/src/components/datapanel/StandardsTab.tsx`
- Create: `frontend/src/components/datapanel/standards/IngestSubTab.tsx`
- Create: `frontend/src/components/datapanel/standards/AnalyzeSubTab.tsx`
- Create: `frontend/src/components/datapanel/standards/standardsApi.ts`
- Modify: `frontend/src/components/DataPanel.tsx` (mount the new tab)

> **Note:** Follow the existing `DomainStandardsTab.tsx` for stylistic conventions
> (colour, button style, table style). The existing project does not have a
> shared `frontend/src/api/` directory, so route wrappers live next to the
> component that consumes them.

- [ ] **Step 1: API wrapper**

Create `frontend/src/components/datapanel/standards/standardsApi.ts`:
```typescript
export interface StdDocumentSummary {
  id: string; doc_code: string; title: string;
  source_type: string; status: string; owner_user_id: string;
}
export interface StdClause { id: string; ordinal_path: string; heading?: string;
  clause_no?: string; kind: string; body_md?: string; }
export interface StdDataElement { id: string; code: string; name_zh: string;
  datatype?: string; obligation: string; }

const j = async <T>(r: Response): Promise<T> => {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
};

export const listDocuments = (params: {owner?: string; status?: string} = {}) => {
  const q = new URLSearchParams(params as Record<string,string>).toString();
  return fetch(`/api/std/documents?${q}`).then(j<{documents: StdDocumentSummary[]}>);
};

export const uploadDocument = (file: File, sourceType: string,
                                sourceUrl?: string) => {
  const fd = new FormData(); fd.append("file", file);
  fd.append("source_type", sourceType);
  if (sourceUrl) fd.append("source_url", sourceUrl);
  return fetch("/api/std/documents", {method: "POST", body: fd})
    .then(j<{document_id: string; version_id: string}>);
};

export const getVersionClauses = (versionId: string) =>
  fetch(`/api/std/versions/${versionId}/clauses`).then(j<{clauses: StdClause[]}>);

export const getVersionDataElements = (versionId: string) =>
  fetch(`/api/std/versions/${versionId}/data-elements`)
    .then(j<{data_elements: StdDataElement[]}>);

export const getVersionTerms = (versionId: string) =>
  fetch(`/api/std/versions/${versionId}/terms`).then(j<{terms: any[]}>);

export const getSimilar = (versionId: string) =>
  fetch(`/api/std/versions/${versionId}/similar`).then(j<{hits: any[]}>);

export const listVersions = (docId: string) =>
  fetch(`/api/std/documents/${docId}/versions`).then(j<{versions: {id: string; version_label: string; status: string}[]}>);
```

- [ ] **Step 2: StandardsTab container**

Create `frontend/src/components/datapanel/StandardsTab.tsx`:
```typescript
import React, { useState } from "react";
import IngestSubTab from "./standards/IngestSubTab";
import AnalyzeSubTab from "./standards/AnalyzeSubTab";

type Sub = "ingest" | "analyze" | "draft" | "review" | "publish" | "derive";

export default function StandardsTab() {
  const [sub, setSub] = useState<Sub>("ingest");
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);

  return (
    <div style={{display:"flex", flexDirection:"column", height:"100%"}}>
      <div style={{display:"flex", gap:8, padding:8, borderBottom:"1px solid #eee"}}>
        {(["ingest","analyze","draft","review","publish","derive"] as Sub[]).map(k => (
          <button key={k}
            onClick={()=>setSub(k)}
            disabled={k!=="ingest" && k!=="analyze"}
            style={{padding:"4px 10px",
              background: sub===k ? "#0a7" : "transparent",
              color: sub===k ? "#fff" : "#444",
              border:"1px solid #ccc", borderRadius:4,
              opacity: (k!=="ingest" && k!=="analyze") ? 0.4 : 1,
              cursor: (k!=="ingest" && k!=="analyze") ? "not-allowed" : "pointer"}}>
            {({ingest:"采集", analyze:"分析", draft:"起草",
               review:"审定", publish:"发布", derive:"派生"} as Record<Sub,string>)[k]}
          </button>
        ))}
      </div>
      <div style={{flex:1, overflow:"auto"}}>
        {sub==="ingest" &&
          <IngestSubTab onPickVersion={setSelectedVersionId} />}
        {sub==="analyze" &&
          <AnalyzeSubTab versionId={selectedVersionId}/>}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: IngestSubTab**

Create `frontend/src/components/datapanel/standards/IngestSubTab.tsx`:
```typescript
import React, { useEffect, useState, useRef } from "react";
import { listDocuments, uploadDocument, listVersions,
         StdDocumentSummary } from "./standardsApi";

interface Props { onPickVersion: (vid: string)=>void; }

export default function IngestSubTab({onPickVersion}: Props) {
  const [docs, setDocs] = useState<StdDocumentSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string|null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => listDocuments().then(r=>setDocs(r.documents)).catch(e=>setErr(String(e)));
  useEffect(()=>{ refresh(); }, []);

  const onUpload = async () => {
    const f = fileRef.current?.files?.[0]; if (!f) return;
    setBusy(true); setErr(null);
    try {
      await uploadDocument(f, "national");
      await refresh();
    } catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  };

  const pickFirstVersion = async (docId: string) => {
    const r = await listVersions(docId);
    if (r.versions.length) onPickVersion(r.versions[0].id);
  };

  return (
    <div style={{padding:12}}>
      <div style={{display:"flex", gap:8, alignItems:"center", marginBottom:12}}>
        <input type="file" ref={fileRef} accept=".docx,.xmi,.pdf"/>
        <button onClick={onUpload} disabled={busy}
          style={{padding:"4px 10px"}}>上传</button>
        {busy && <span>处理中…</span>}
        {err && <span style={{color:"red"}}>{err}</span>}
      </div>
      <table style={{width:"100%", borderCollapse:"collapse"}}>
        <thead><tr style={{background:"#f4f4f4"}}>
          <th>编号</th><th>标题</th><th>类型</th><th>状态</th><th>操作</th>
        </tr></thead>
        <tbody>
          {docs.map(d=>(
            <tr key={d.id} style={{borderBottom:"1px solid #eee"}}>
              <td>{d.doc_code}</td><td>{d.title}</td>
              <td>{d.source_type}</td><td>{d.status}</td>
              <td><button onClick={()=>pickFirstVersion(d.id)}>查看条款</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: AnalyzeSubTab**

Create `frontend/src/components/datapanel/standards/AnalyzeSubTab.tsx`:
```typescript
import React, { useEffect, useState } from "react";
import { getVersionClauses, getVersionDataElements, getVersionTerms,
         getSimilar, StdClause, StdDataElement } from "./standardsApi";

interface Props { versionId: string | null; }

export default function AnalyzeSubTab({versionId}: Props) {
  const [clauses, setClauses] = useState<StdClause[]>([]);
  const [des, setDes] = useState<StdDataElement[]>([]);
  const [terms, setTerms] = useState<any[]>([]);
  const [similar, setSimilar] = useState<any[]>([]);

  useEffect(()=>{
    if (!versionId) return;
    Promise.all([
      getVersionClauses(versionId).then(r=>setClauses(r.clauses)),
      getVersionDataElements(versionId).then(r=>setDes(r.data_elements)),
      getVersionTerms(versionId).then(r=>setTerms(r.terms)),
      getSimilar(versionId).then(r=>setSimilar(r.hits)).catch(()=>setSimilar([])),
    ]);
  }, [versionId]);

  if (!versionId) return <div style={{padding:24, color:"#888"}}>
    请在"采集"Tab 选择一个文档查看条款。</div>;

  return (
    <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:12, padding:12}}>
      <div>
        <h4>条款树（{clauses.length}）</h4>
        <ul style={{maxHeight:280, overflow:"auto"}}>
          {clauses.map(c=>(
            <li key={c.id}><b>{c.clause_no}</b> {c.heading}
              <div style={{color:"#666", fontSize:12, marginLeft:8}}>{c.body_md?.slice(0,80)}</div>
            </li>
          ))}
        </ul>
        <h4>术语（{terms.length}）</h4>
        <ul style={{maxHeight:120, overflow:"auto"}}>
          {terms.map((t:any)=>(<li key={t.id}>{t.term_code} — {t.name_zh}</li>))}
        </ul>
      </div>
      <div>
        <h4>数据元（{des.length}）</h4>
        <table style={{width:"100%", fontSize:13}}>
          <thead><tr><th>code</th><th>name_zh</th><th>datatype</th><th>oblig.</th></tr></thead>
          <tbody>
            {des.map(d=>(<tr key={d.id}><td>{d.code}</td><td>{d.name_zh}</td>
              <td>{d.datatype}</td><td>{d.obligation}</td></tr>))}
          </tbody>
        </table>
        <h4>相似条款（{similar.length}）</h4>
        <ul style={{maxHeight:160, overflow:"auto"}}>
          {similar.map((h:any,i:number)=>(
            <li key={i}>v={h.document_version_id.slice(0,8)} sim={h.similarity.toFixed(3)}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Mount in DataPanel.tsx**

Open `frontend/src/components/DataPanel.tsx`. Find where existing tabs are
imported and rendered (search for `DomainStandardsTab` or `KnowledgeBaseTab`).
Add:

```typescript
import StandardsTab from "./datapanel/StandardsTab";
```

and in the tab definition list (whatever shape it has — string array, object
list, switch statement) add a new entry titled `数据标准` that renders
`<StandardsTab/>`. Match the pattern of the most-recent tab added to the file.

- [ ] **Step 6: Build + commit**

```
cd frontend && npm run build && cd ..
git add frontend/src/components/datapanel/StandardsTab.tsx frontend/src/components/datapanel/standards frontend/src/components/DataPanel.tsx
git commit -m "feat(std-platform): frontend StandardsTab + Ingest/Analyze sub-tabs"
```

## Task 22: Env config, roadmap, regression sweep, end-to-end smoke

**Files:**
- Modify: `data_agent/.env` (developer machine — not committed) and `data_agent/.env.sample` if it exists
- Modify: `docs/roadmap.md`
- Modify: `requirements.txt` (only if needed; project already has `requests`)

- [ ] **Step 1: Add env vars**

Append to your developer `.env` (do NOT commit secrets to repo):
```
STANDARDS_WEB_DOMAINS_ALLOWLIST=std.samr.gov.cn,openstd.samr.gov.cn,ogc.org,iso.org,arxiv.org,scholar.google.com,cnki.net
STANDARDS_OUTBOX_WORKER_INTERVAL_SEC=5
STANDARDS_OUTBOX_MAX_ATTEMPTS=5
```

If a tracked `data_agent/.env.sample` exists, mirror those keys with placeholder
values there too.

- [ ] **Step 2: Update roadmap**

Open `docs/roadmap.md` and add a new entry under the most recent "next up"
section (mirror the file's existing heading style):

```markdown
### v25.x — 数据标准全生命周期智能化平台 (Standards Platform)

- **P0 (本期落地)**：采集 + 分析底座 — 16 张 std_* 表 + Outbox 独立 worker
  + ltree + pgvector(768) + 12 个 REST + StandardsTab 两个 sub-tab。
  Spec: `docs/superpowers/specs/2026-05-13-data-standard-lifecycle-platform-design.md`
- **P1**：起草（TipTap + 引用助手 + 一致性校验）+ StandardsEditorAgent (Agent #7)
- **P2**：审定 + 发布 + 派生（6 strategy；标准 → semantic_hints / value_semantics
  / synonyms / qc_rules / defect_taxonomy 单向派生）
- **P3**：to_data_model — CDM/LDM/PDM 三层 + DDL + 反向 XMI（替代 EA 工作流）
- **P4**：审定流模板可视化、批量回滚、跨标准影响图谱
```

- [ ] **Step 3: Regression sweep — full project test run**

```
.venv/Scripts/python.exe -m pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q
```
Expected: all green. If any pre-existing test now fails, **stop and triage**
before going further. Likely cause if anything fails: migration 075 added the
`std_derived_link_id` column to a downstream table that an existing test
inserts into without specifying all columns — fix by either making the test
explicit or confirming the column is nullable (it is).

- [ ] **Step 4: Frontend build**

```
cd frontend && npm run build && cd ..
```
Expected: exits 0; check for TypeScript errors related to the new tab.

- [ ] **Step 5: End-to-end smoke (manual)**

1. Apply migrations: `.venv/Scripts/python.exe -m data_agent.migration_runner`
2. Start chainlit: `$env:PYTHONPATH = "D:\adk"; chainlit run data_agent/app.py -w`
3. In a second terminal, start the worker:
   `$env:PYTHONPATH = "D:\adk"; .venv/Scripts/python.exe -m data_agent.standards_platform.outbox_worker`
4. Log in as `admin` / `admin123`.
5. DataPanel → "数据标准" tab → "采集" → upload a real `GB-T-13923-2022.docx`
   (or any test docx).
6. Wait up to 10 minutes. Confirm via SQL:
   ```
   SELECT status, COUNT(*) FROM std_outbox GROUP BY status;
   SELECT COUNT(*) FROM std_clause WHERE document_version_id IN
     (SELECT current_version_id FROM std_document WHERE doc_code LIKE 'GB%');
   ```
   Expected: outbox has `done` rows, no `failed` rows; ≥ 20 clauses present.
7. Switch to "分析" sub-tab — verify clause tree, data elements, terms render.
8. Upload a second overlapping standard. After processing, check
   `/api/std/versions/{v}/similar` returns hits ≥ 80 % of overlapping clauses.
9. Kill the worker mid-pipeline; confirm `std_outbox` rows are still
   `pending`/`in_flight`. Restart worker — confirm pipeline resumes and
   the doc reaches `status='drafting'`.

- [ ] **Step 6: Final commit**

```
git add docs/roadmap.md
git commit -m "docs(roadmap): add v25.x Standards Platform entry"
```

If `requirements.txt` needed any new dep (none expected for P0), commit
separately:
```
git add requirements.txt
git commit -m "chore: pin std-platform deps"
```

---

## Wrap-up

After Task 22 is green:
- Confirm `git log --oneline` shows ~22 small commits with `feat(std-platform):`
  and `docs(roadmap):` prefixes.
- The Standards Platform P0 is now usable end-to-end: ingest → structure → embed → dedupe.
- Subsequent stages (drafting / review / publishing / derivation) each get their
  own spec + plan; do NOT extend this plan to cover them.
