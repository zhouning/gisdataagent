# ADR-186: Governed ER model canvas and versioned editing

## Status

Proposed

## Context

GIS Data Agent can display immutable CDM/LDM/PDM snapshots and export DDL/XMI,
but the snapshot preview previously exposed entities and relationships only as
lists or raw JSON. DMT has also imported the candidate PDM into an Enterprise
Architect repository. Users need an intuitive ER canvas and ultimately need to
manage model changes without losing auditability or creating two competing
authoritative models.

Current constraints:

- `std_data_model_snapshot` is an immutable derived/manual artefact, not an
  editable normalized model store.
- The existing API is read-only and prioritizes `active` over `manual`
  snapshots.
- DMT keys, value domains, SRIDs, sensitivities, and some semantic relations
  remain candidates.
- EA is a review and publication target; direct repository writes would bypass
  GIS Data Agent validation and approval controls.

## Options considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Write directly to the EA repository | Changes appear immediately in EA | Couples to EA internals, bypasses approval, unsafe concurrent edits | Rejected |
| Mutate `std_data_model_snapshot.pdm_json` in place | Small implementation | Destroys provenance and makes published models non-reproducible | Rejected |
| Keep browser read-only forever | Safest and simplest | Does not support collaborative model management | Interim only |
| Versioned draft changesets with validation and approval | Auditable, reversible, supports EA export and impact analysis | Requires draft/revision APIs and workflow UI | Chosen |

## Decision

1. Provide a read-only interactive ER canvas immediately from the preferred
   snapshot. Nodes may be moved for inspection, but layout movement does not
   change model content.
2. Treat model editing as a versioned workflow, not direct JSON or EA mutation:
   `base snapshot → draft revision → validation → review/approval → new snapshot`.
3. Store layout metadata separately from semantic changes. Moving a node is a
   presentation preference; adding an entity, field, key, relationship, type,
   value domain, sensitivity, or SRID is a governed model operation.
4. Every draft records the base snapshot ID and SHA-256. Optimistic locking
   rejects edits based on a stale base.
5. Server-side validation must cover unique table/column identifiers, PK/FK
   targets, relationship endpoints and cardinalities, types, sensitivity,
   geometry/SRID policy, DDL rendering, XMI rendering, and DMT-125S impact.
6. Publication creates a new immutable snapshot and an audit/outbox event. It
   never overwrites an `active` or `manual` snapshot.
7. EA synchronization remains explicit: publish an XMI/change package or use a
   future controlled adapter. GIS Data Agent must not write directly to EA
   repository tables.

## Initial canvas scope

- Domain focus and full-model mode
- Search by entity, physical table, or field
- Optional one-hop cross-domain neighbours
- PK/FK/type display and relationship cardinality labels
- Zoom, pan, minimap, fit-to-view, and local node movement
- Double-click from canvas into the complete entity/field browser
- Explicit read-only/candidate status

## Consequences

### Positive

- DMT's 79 entities and 223 relationships become understandable without
  reading JSON or manually building an EA diagram.
- Snapshot provenance and active/manual precedence remain intact.
- Future edits can be reviewed, compared, rolled back, exported to EA, and
  linked to affected benchmark questions.

### Negative

- Full content editing requires new normalized draft/change tables, APIs,
  authorization, tests, and approval integration.
- GIS Data Agent and EA can diverge until an explicit publication/sync step is
  completed.

### Mitigation

- Show snapshot hash, EA package GUID, mapping status, and divergence state.
- Require impact and validation reports before approval.
- Keep all EA access read-only until a separately approved adapter exists.

## Revisit triggers

- DMT designates EA, rather than GIS Data Agent, as the authoritative model
  editor.
- Multi-user real-time editing becomes a requirement.
- EA offers a supported API with transaction, conflict, and audit guarantees
  sufficient to replace XMI-based synchronization.
