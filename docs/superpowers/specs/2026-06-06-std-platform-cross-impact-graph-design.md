# Standards Platform Cross-Standard Impact Graph First Slice Design

- **Status**: Approved for implementation planning
- **Date**: 2026-06-06
- **Scope**: P4 cross-standard impact graph first slice
- **Builds on**: `link_repo.impact_graph()`, `std_derived_link`,
  `std_reference`, `deduper.find_similar_clauses()`, and `AnalyzeSubTab`

## 1. Goal

Add a version-level impact graph view so an operator can inspect how one
standard document version connects to derived governance artefacts and to other
standards. This first slice aggregates existing relationships into a read-only
graph response:

1. derivation edges from `std_derived_link`
2. reference edges from `std_reference`
3. similar-clause edges from the existing pgvector deduper

The graph is intentionally operational and compact. It is meant to answer
"what does this standard version affect or depend on?" without adding new graph
storage, graph layout infrastructure, or write workflows.

## 2. In Scope

1. **Repository graph builder**:
   `data_agent/standards_platform/analysis/impact_graph.py` with
   `version_impact_graph(version_id, include_similar=True, min_similarity=0.8,
   top_k=20)`.
2. **API**:
   `GET /api/std/impact/versions/{version_id}` returning `{version_id, nodes,
   edges, summary}` for authenticated users.
3. **Frontend SDK**:
   typed `getVersionImpactGraph(versionId, params?)` in `standardsApi.ts`.
4. **Analyze UI first slice**:
   add a compact graph summary and edge list in `AnalyzeSubTab`.
5. **Roadmap update**:
   mark P4 cross-standard impact graph first slice complete.

## 3. Non-Goals

- No new database tables or migrations.
- No graph persistence, graph layout engine, or force-directed canvas.
- No editable dependency graph.
- No impact preview modal for rollback.
- No recursive multi-hop traversal in this slice.
- No LLM-generated explanation of graph edges.

## 4. Response Shape

```json
{
  "version_id": "...",
  "nodes": [
    {
      "id": "version:<uuid>",
      "kind": "version",
      "label": "DOC v1.0",
      "document_id": "...",
      "version_id": "...",
      "metadata": {"doc_code": "...", "title": "...", "status": "released"}
    }
  ],
  "edges": [
    {
      "id": "derive:<link_id>",
      "edge_type": "derives",
      "source": "data_element:<uuid>",
      "target": "semantic_hint:<id>",
      "label": "to_semantic_hint",
      "status": "active",
      "metadata": {"target_table": "agent_semantic_hints"}
    },
    {
      "id": "reference:<ref_id>",
      "edge_type": "references",
      "source": "clause:<uuid>",
      "target": "clause:<uuid>",
      "label": "std_clause",
      "status": "pending",
      "metadata": {"citation_text": "..."}
    },
    {
      "id": "similar:<source_clause_id>:<target_clause_id>",
      "edge_type": "similar_clause",
      "source": "clause:<uuid>",
      "target": "clause:<uuid>",
      "label": "similar 0.912",
      "score": 0.912,
      "metadata": {"target_version_id": "..."}
    }
  ],
  "summary": {
    "node_count": 10,
    "edge_count": 9,
    "by_edge_type": {"derives": 4, "references": 2, "similar_clause": 3},
    "cross_version_edge_count": 5
  }
}
```

Node IDs are stable graph IDs, not necessarily database primary keys. Edges
carry database IDs in `id` or `metadata` where available.

## 5. Backend Design

### Repository

`version_impact_graph()` builds graph nodes through a small local `add_node()`
helper that deduplicates by graph ID.

Derivation edges:

- query `std_derived_link WHERE source_version_id=:version_id`
- include source nodes from `source_kind/source_id`
- include target nodes from `target_kind/target_id`
- edge metadata includes `derivation_strategy`, `target_table`,
  `generated_at`, and link `status`

Reference edges:

- source clauses are clauses under the requested version
- include `std_reference` rows sourced from those clauses
- resolve target nodes for `std_clause`, `std_data_element`, `std_term`,
  `std_document`, and external targets
- mark cross-version edges when the resolved target version differs from the
  requested version

Similar-clause edges:

- call `deduper.find_similar_clauses(version_id=..., top_k=..., min_similarity=...)`
- add source and target clause nodes
- mark all similar-clause edges as cross-version because deduper excludes the
  source version

### API

`GET /api/std/impact/versions/{version_id}`:

- any authenticated user can read
- validates that `version_id` exists, returning
  `404 {"error": "version not found"}`
- query params:
  - `include_similar`: default `1`; `0` disables deduper edges
  - `min_similarity`: float, default `0.8`
  - `top_k`: integer, default `20`, capped at `100`
- malformed numeric params return `400`
- route must be registered before `/api/std/impact/{kind}/{source_id}`

## 6. Frontend Design

`AnalyzeSubTab` keeps the current two-column analysis layout and adds a compact
third section for impact graph:

- summary chips: total nodes, total edges, derives, references, similar
- a scrollable edge list grouped by `edge_type`
- refreshes when `versionId` changes
- shows an error message if graph loading fails
- does not render a force graph or canvas in this slice

## 7. Testing Strategy

Use TDD for backend behavior.

Repository tests:

- returns root version node and derivation edges
- includes reference edges across versions
- includes similar-clause edges when deduper returns hits
- can disable similar edges

API tests:

- unauthenticated gets `401`
- missing version gets `404`
- invalid numeric params get `400`
- happy path delegates to repository and returns result
- static route does not get shadowed by `/api/std/impact/{kind}/{source_id}`

Frontend:

- `npm run build` is required verification; no React test harness exists in
  this area.

Regression:

- focused impact graph tests
- full `data_agent/standards_platform` suite
- frontend build

## 8. Acceptance Criteria

- A selected standard version can return one graph response with derivation,
  reference, and similar-clause edges.
- Cross-version edges are counted in the summary.
- Existing single-source impact API remains compatible.
- Analyze tab exposes a compact, readable graph summary and edge list.
- Focused backend tests, full Standards Platform tests, and frontend build pass.
