# ADR-178: Display a curated DMT structure model through the standard snapshot API

## Status

Accepted

## Context

The Abu Dhabi Department of Municipalities and Transport (DMT) supplied model
structure clues, but record-level data and customer confirmation are not yet
available. GIS Data Agent still needs a reviewable model so that domains,
entities, attributes, relationships, provenance, and uncertainty can be
discussed in the product.

The existing Standards Platform already stores CDM/LDM/PDM/DDL artefacts in
`std_data_model_snapshot`, but its read endpoints only selected snapshots with
`derived_status='active'`. A manual import must not execute DMT DDL, create
business tables, or create an automatic derivation link.

## Decision

1. Import the DMT package as a `draft` `std_document` with a `draft`
   `std_document_version` and a `manual` `std_data_model_snapshot`.
2. Make the import idempotent using a content SHA-256 in `source_tag`; repeat
   imports of identical content reuse the existing snapshot.
3. Select `active` snapshots first in the read API. If no active snapshot exists,
   select the latest `manual` candidate. Preserve `derived_status` in the API
   response so the UI can label the model as a candidate.
4. Present a domain/entity/attribute master-detail browser and a searchable
   relationship view by default. Keep raw CDM/LDM/PDM JSON, DDL copy/download,
   and XMI download for engineering workflows.

## Trade-offs

- The candidate model is immediately reviewable, but it is not a substitute
  for customer confirmation or record-level profiling.
- A manual snapshot remains a JSONB artefact rather than normalized model
  tables; this avoids schema churn and keeps immutable payload provenance, at
  the cost of doing client-side filtering for the review view.
- A future active derivation takes precedence over a manual candidate. This
  preserves the existing authoritative semantics; curators must avoid running
  an automatic derivation against an unprepared version.

## Consequences

- DMT appears in the normal Standards Platform document/version workflow and
  the existing data-model button can display it without a separate frontend
  route.
- The import script explicitly reports `ddl_executed=false` and
  `derived_link_created=false`, providing a safe audit boundary.
- Once DMT confirms source ownership, keys, SRIDs, sensitivity, and refresh
  contracts, the candidate can be superseded by a derived or approved version.
