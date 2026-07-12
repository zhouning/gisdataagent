# Public Feedback Demand 15 Design

## Objective

Implement a public/customer feedback evidence-ingestion and spatial-semantic readiness product without treating platform agent votes as urban public opinion or fabricating sentiment, satisfaction, complaint hotspots, public preferences or policy effects.

## Method Ownership

- Traditional NLP/GIS owns ingestion, deduplication, privacy filtering, language detection, taxonomy mapping, geocoding, temporal aggregation and descriptive spatial summaries.
- UWM may receive validated feedback observations as a partial, biased perception channel attached to place and time.
- UWM may not treat feedback as ground truth population state, causal impact, representative preference or policy response without sampling, calibration and longitudinal outcome evidence.

## Feedback Observation Contract

Required fields:

- observation identifier
- source system and collection method
- collection timestamp and time zone
- consent/legal basis and retention policy
- text or structured response
- language
- spatial reference type and original location evidence
- geocoding method and confidence
- issue taxonomy and classifier version
- deduplication group
- demographic or sampling frame metadata where legally available
- provenance and quality flags

Personally identifying information must be removed or separately protected before analysis publication.

## Channels

- public consultation submissions
- complaints and service requests
- resident surveys
- customer interviews
- community workshop notes
- online platform comments
- call-centre transcripts
- geocoded feedback observations
- issue taxonomy
- sentiment labels
- satisfaction measures
- response and resolution records
- longitudinal feedback outcomes

All channels remain unavailable until authoritative customer data are connected.

## Analysis Gate

The following mechanisms remain closed without real corpus evidence:

- deduplicated corpus construction
- privacy-safe publication
- issue classification
- sentiment estimation
- satisfaction estimation
- spatial hotspot detection
- temporal trend detection
- representativeness weighting
- response-time analysis
- feedback-to-intervention linkage
- UWM perception-state update
- policy-response or satisfaction prediction

## Capability Catalog

Repository capabilities may be catalogued when backed by code: platform agent feedback storage, geocoding, knowledge-base text chunking/embedding, semantic ontology and generic analytics. These are capabilities only and are not city feedback observations.

## Claim Boundary

Maximum claim: `public_feedback_data_contract_spatial_semantic_and_uwm_observation_readiness`.

Mandatory exclusions:

- agent upvote/downvote is not urban public opinion
- text volume is not issue severity
- sentiment is not satisfaction
- geocoded mention is not incident confirmation
- hotspot is not representative prevalence
- feedback association is not policy effect
- missing feedback is not absence of concern

## Publication

Publish six files: `overview.json`, `capabilities.json`, `feedback_channels.json`, `data_contracts.json`, `analysis_gate.json`, and `map.json`; expose authenticated APIs and an independent `公众反馈证据` tab.
