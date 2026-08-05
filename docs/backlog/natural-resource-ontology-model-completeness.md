# Natural-resource ontology model completeness backlog

Status: OPEN

Priority: P0 before the next customer-facing ontology release

Owner: Natural-resource ontology workstream

Target: Continue in the next working session; do not treat V2.0.1 as a complete
domain ontology.

## Problem statement

The current Natural Resource One Map V2.0.1 package is sufficient to exercise
the governed runtime, SPARQL projection, conversational query path, OKF
computation contracts, and customer demo. It is not yet sufficiently complete
or coherent as a natural-resource domain ontology.

The model must not be presented as complete merely because it loads in
Protege, has many generated classes, or supports the current demo queries.
Application functions such as "intelligent data inquiry" are not domain
classes. Table names, UI functions, document headings, data fields, domain
entities, states, processes, rules, and evidence must remain in separate
modeling layers.

The user has explicitly rejected the current level of ontology completeness.
This backlog remains open until the acceptance criteria below are met.

## Required next-session work

1. Re-audit the EA repository and the source standards, retaining a traceable
   source reference for every accepted concept, relation, property, value
   domain, and constraint.
2. Define modeling boundaries and upper categories before expanding the class
   count: resource entity, spatial unit, legal/management unit, observed state,
   planned state, event/process, actor, right/restriction, rule, evidence, and
   dataset/schema mapping.
3. Rebuild the land core taxonomy using domain semantics rather than source
   table structure. At minimum, model Land as the core concept; Agricultural
   Land, Construction Land, and Unused Land as classified land categories;
   Cultivated Land and Non-cultivated Agricultural Land as Agricultural Land
   specializations.
4. Model change correctly. Agricultural restructuring and construction
   occupation are processes/events with participants, preconditions, source
   state/category, target state/category, time, authority, evidence, and
   governing rules. They are not `subClassOf` shortcuts and are not loose text
   labels on a class.
5. Separate asserted facts from inferred facts, and separate OWL axioms from
   SHACL validation rules and executable spatial/business rules.
6. Review Chinese preferred labels, synonyms, definitions, stable IRIs,
   disjointness, domain/range, cardinality, inverse relations, and temporal
   validity. Remove generated or imported terms that have no defensible domain
   meaning.
7. Add competency questions covering hierarchy, allowed and prohibited land
   transitions, rights/restrictions, planning controls, cross-department term
   alignment, schema binding, provenance, and spatially qualified queries.
8. Run reasoner and SHACL validation, document unsatisfiable classes and
   violations, and publish a reviewable Protege artifact only after the model
   passes the agreed quality gates.

## Acceptance criteria

- A domain expert can explain every top-level class and object property without
  referring to a database table or application screen.
- No UI capability, report name, tool name, or workflow label is modeled as a
  natural-resource domain class unless it denotes a defensible domain process.
- The Land taxonomy and its conversion processes answer the agreed competency
  questions through OWL/SPARQL, with the source and inference path visible.
- Concepts imported from EA and standards have explicit provenance and review
  disposition: accepted, mapped, deprecated, or rejected.
- OWL DL reasoning reports no unintended unsatisfiable named classes.
- SHACL validation and regression tests cover the curated model rather than
  only package structure and API behavior.
- Protege opens the released artifact with the expected hierarchy, labels,
  object properties, restrictions, annotations, and ontology version IRI.
- A versioned completeness report lists modeled coverage, known gaps, rejected
  candidates, competency-question results, and expert review decisions.

## Non-closure conditions

Passing the existing runtime tests, OKF attestation tests, frontend build, or
demo E2E does not close this backlog. Those checks validate the application
integration around the ontology, not the semantic completeness or professional
quality of the ontology itself.
