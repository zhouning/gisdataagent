---
type: Ontology Asset
title: Natural-resource one-map ontology
description: Governed OWL/RDF semantics for natural-resource concepts, states, processes, evidence, and data assets.
resource: /api/ontology/export/turtle
tags: [natural-resource, ontology, owl, rdf]
status: stable
generated: { by: gda-ontology-publisher/2.1.0, at: 2026-08-05T08:16:25Z }
verified: { by: process:gda-ontology-release-gate, at: 2026-08-05T08:16:25Z }
sources:
  - id: ontology-package
    resource: /sources/ontology-package.md
    title: Natural-resource ontology immutable package V2.1.0
---

# Role

The ontology is the authoritative formal semantic model used by Fuseki/SPARQL
and the governed ontology query gateway. OKF documents its business meaning and
provenance; it does not replace OWL, SHACL, SPARQL, or the RDF store.

# Core Model

Land is specialized into agricultural land, construction land, and unused land.
Land parcels are separate spatial units connected to land through a governed
object property. Observed and planned land-use states are connected through
processes such as agricultural structure adjustment, construction occupation,
reclamation, and consolidation.

See the [land-use transition model](/assets/land-use-transition-model.md).
