from __future__ import annotations

import hashlib
import json
from copy import deepcopy


CHANNELS = ("public_consultation", "complaints_service_requests", "resident_surveys", "customer_interviews", "community_workshops", "online_comments", "call_centre_transcripts", "geocoded_feedback", "issue_taxonomy", "sentiment_labels", "satisfaction_measures", "response_resolution_records", "longitudinal_feedback_outcomes")


def build_public_feedback_readiness_product(*, capabilities, source_artifacts):
    items = deepcopy(capabilities)
    for item in items:
        if not item.get("source_path"):
            raise ValueError("feedback_capability_source_required")
        if item.get("status") == "observed_public_feedback":
            raise ValueError("platform_feedback_not_public_observation")
    channels = {name: {"status": "unavailable", "value": None, "record_count": None, "spatial_coverage": None, "temporal_coverage": None, "production_blockers": ["authoritative_privacy_safe_customer_feedback_corpus_missing"]} for name in CHANNELS}
    contracts = {"feedback_observation": {"required_fields": ["observation_id", "source_system", "collection_method", "collection_timestamp", "time_zone", "consent_or_legal_basis", "retention_policy", "text_or_structured_response", "language", "spatial_reference_type", "original_location_evidence", "geocoding_method", "geocoding_confidence", "issue_taxonomy", "classifier_version", "deduplication_group", "sampling_frame_metadata", "provenance", "quality_flags"], "privacy_requirements": ["remove_or_protect_personally_identifying_information", "publish_only_authorized_aggregates"]}}
    mechanisms = ("deduplicated_corpus_construction", "privacy_safe_publication", "issue_classification", "sentiment_estimation", "satisfaction_estimation", "spatial_hotspot_detection", "temporal_trend_detection", "representativeness_weighting", "response_time_analysis", "feedback_intervention_linkage", "uwm_perception_state_update", "policy_response_prediction", "satisfaction_prediction")
    gate = {"status": "closed", "mechanisms": {name: "closed" for name in mechanisms}, "uwm_observation_status": "closed", "uwm_observation_limitations": ["feedback_is_partial_biased_perception_channel", "not_population_ground_truth", "not_causal_outcome"]}
    digest = {"capabilities": items, "channels": channels}
    bundle_id = "public-feedback-" + hashlib.sha256(json.dumps(digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return {"schema": "uwm.public_feedback_readiness.v1", "bundle_id": bundle_id, "summary": {"capability_count": len(items), "feedback_channel_count": len(channels), "available_feedback_channel_count": 0, "open_analysis_mechanism_count": 0, "published_feedback_observation_count": 0}, "capabilities": items, "feedback_channels": channels, "data_contracts": contracts, "analysis_gate": gate, "source_artifacts": sorted(map(str, source_artifacts)), "claim_boundary": {"max_claim_level": "public_feedback_data_contract_spatial_semantic_and_uwm_observation_readiness", "agent_vote_not_urban_public_opinion": True, "text_volume_not_issue_severity": True, "sentiment_not_satisfaction": True, "geocoded_mention_not_incident_confirmation": True, "hotspot_not_representative_prevalence": True, "feedback_association_not_policy_effect": True, "missing_feedback_not_absence_of_concern": True}, "fabricated_value_count": 0}
