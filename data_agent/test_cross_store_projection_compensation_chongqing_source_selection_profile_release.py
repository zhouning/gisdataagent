from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent.chongqing_entity_link_baseline import CUSTOMER_BUNDLE_DIR
from data_agent.cross_store_projection_compensation_chongqing_deployment import (
    build_chongqing_federated_compensation_source_catalog,
)
from data_agent.cross_store_projection_compensation_chongqing_source_selection_profile import (
    build_chongqing_federated_compensation_profiled_source_lineage_binding,
    build_chongqing_federated_compensation_source_selection_profile,
)
from data_agent.cross_store_projection_compensation_chongqing_source_selection_profile_release import (  # noqa: E501
    ChongqingSourceSelectionProfileReleaseError,
    ChongqingSourceSelectionProfileReleaseHistory,
    build_chongqing_source_selection_profile_execution_release_binding,
    build_initial_chongqing_source_selection_profile_release_history,
    publish_chongqing_source_selection_profile_change,
    rollback_chongqing_source_selection_profile_release,
)
from data_agent.test_cross_store_projection_compensation_chongqing_source_selection_profile import (  # noqa: E501
    _profiled_lineage_inputs,
)

_RELEASE_HISTORY_ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "reports"
    / "chongqing_source_selection_profile_release_history_2026-08-18.json"
)


def _profile(bundle_dir: Path | None = None):
    catalog = build_chongqing_federated_compensation_source_catalog(bundle_dir=bundle_dir)
    return build_chongqing_federated_compensation_source_selection_profile(
        catalog,
        "heping_review",
        bundle_dir=bundle_dir,
    )


def _revised_profile(tmp_path: Path):
    bundle_dir = tmp_path / "revised-customer-bundle"
    shutil.copytree(CUSTOMER_BUNDLE_DIR, bundle_dir)
    demo_path = bundle_dir / "demo.json"
    demo = json.loads(demo_path.read_text(encoding="utf-8"))
    scenario = next(item for item in demo["scenarios"] if item["id"] == "heping_review")
    scenario["label"] = f"{scenario['label']}（技术修订）"
    demo_path.write_text(
        json.dumps(demo, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["name"] == "demo.json")
    entry["size"] = demo_path.stat().st_size
    entry["sha256"] = hashlib.sha256(demo_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return _profile(bundle_dir)


def test_initial_profile_publication_is_deterministic_and_non_authorizing() -> None:
    profile = _profile()
    first = build_initial_chongqing_source_selection_profile_release_history(profile)
    second = build_initial_chongqing_source_selection_profile_release_history(profile)

    assert first == second
    assert len(first.releases) == 1
    release = first.active_release
    assert release.release_version == 1
    assert release.event_kind == "initial_publication"
    assert release.source_selection_profile_sha256 == profile.profile_sha256
    assert release.predecessor_release_sha256 is None
    assert release.ancestor_release_sha256s == ()
    assert first.active_release_sha256 == release.release_sha256
    assert first.customer_approval_present is False
    assert first.production_execution_authorized is False
    assert first.authority_write_performed is False
    document = first.model_dump_json()
    assert "relative_path" not in document
    assert '"features"' not in document
    assert "provider_commit_ref" not in document


def test_published_v1_history_artifact_matches_current_sealed_profile() -> None:
    artifact = ChongqingSourceSelectionProfileReleaseHistory.model_validate_json(
        _RELEASE_HISTORY_ARTIFACT.read_text(encoding="utf-8")
    )
    rebuilt = build_initial_chongqing_source_selection_profile_release_history(_profile())

    assert artifact == rebuilt
    assert len(artifact.releases) == 1
    assert artifact.active_release.event_kind == "initial_publication"
    assert artifact.customer_approval_present is False
    assert artifact.production_execution_authorized is False
    assert artifact.authority_write_performed is False


def test_active_release_binds_exact_execution_inputs_without_authorizing(
    tmp_path: Path,
) -> None:
    source_catalog, deployment_binding, profile, source_lineage_set = _profiled_lineage_inputs()
    profiled_binding = build_chongqing_federated_compensation_profiled_source_lineage_binding(
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
    )
    history = build_initial_chongqing_source_selection_profile_release_history(
        profile,
        tenant_id=deployment_binding.tenant_id,
    )

    release_binding = build_chongqing_source_selection_profile_execution_release_binding(
        history,
        profile,
        deployment_binding,
        profiled_binding,
    )

    assert release_binding.active_release_sha256 == history.active_release_sha256
    assert release_binding.release_history_sha256 == history.history_sha256
    assert release_binding.source_selection_profile_sha256 == profile.profile_sha256
    assert release_binding.provider_dispatch_performed is False
    assert release_binding.customer_approval_present is False
    assert release_binding.production_execution_authorized is False
    assert release_binding.authority_write_performed is False

    foreign_history = build_initial_chongqing_source_selection_profile_release_history(
        profile,
        tenant_id="another-tenant",
    )
    with pytest.raises(
        ChongqingSourceSelectionProfileReleaseError,
        match="differs from execution inputs",
    ):
        build_chongqing_source_selection_profile_execution_release_binding(
            foreign_history,
            profile,
            deployment_binding,
            profiled_binding,
        )

    revised_history = publish_chongqing_source_selection_profile_change(
        history,
        _revised_profile(tmp_path),
        change_reason="temporary active-release drift rehearsal",
    )
    with pytest.raises(
        ChongqingSourceSelectionProfileReleaseError,
        match="differs from execution inputs",
    ):
        build_chongqing_source_selection_profile_execution_release_binding(
            revised_history,
            profile,
            deployment_binding,
            profiled_binding,
        )


def test_changed_profile_appends_contiguous_release_with_predecessor(tmp_path: Path) -> None:
    initial_profile = _profile()
    revised_profile = _revised_profile(tmp_path)
    history = build_initial_chongqing_source_selection_profile_release_history(initial_profile)

    changed = publish_chongqing_source_selection_profile_change(
        history,
        revised_profile,
        change_reason="customer scenario evidence technical revision",
    )

    assert tuple(item.release_version for item in changed.releases) == (1, 2)
    release = changed.active_release
    assert release.event_kind == "profile_change"
    assert release.predecessor_release_sha256 == history.active_release_sha256
    assert release.ancestor_release_sha256s == (history.active_release_sha256,)
    assert release.source_selection_profile_sha256 == revised_profile.profile_sha256
    assert release.source_selection_profile_sha256 != initial_profile.profile_sha256
    assert changed.active_release_sha256 == release.release_sha256


def test_rollback_appends_new_release_and_restores_exact_prior_profile(
    tmp_path: Path,
) -> None:
    initial_profile = _profile()
    revised_profile = _revised_profile(tmp_path)
    initial = build_initial_chongqing_source_selection_profile_release_history(initial_profile)
    changed = publish_chongqing_source_selection_profile_change(
        initial,
        revised_profile,
        change_reason="customer scenario evidence technical revision",
    )

    rolled_back = rollback_chongqing_source_selection_profile_release(
        changed,
        initial.active_release_sha256,
        initial_profile,
        change_reason="restore the prior sealed technical profile",
    )

    assert tuple(item.release_version for item in rolled_back.releases) == (1, 2, 3)
    release = rolled_back.active_release
    assert release.event_kind == "rollback"
    assert release.rollback_target_release_sha256 == initial.active_release_sha256
    assert release.predecessor_release_sha256 == changed.active_release_sha256
    assert release.ancestor_release_sha256s == tuple(
        item.release_sha256 for item in changed.releases
    )
    assert release.source_selection_profile_sha256 == initial_profile.profile_sha256
    assert release.customer_approval_present is False
    assert release.production_execution_authorized is False


def test_profile_release_governance_rejects_noop_foreign_and_tampered_transitions(
    tmp_path: Path,
) -> None:
    profile = _profile()
    history = build_initial_chongqing_source_selection_profile_release_history(profile)

    with pytest.raises(ChongqingSourceSelectionProfileReleaseError, match="cannot be sealed"):
        build_initial_chongqing_source_selection_profile_release_history(
            profile,
            change_reason=" ",
        )

    with pytest.raises(ChongqingSourceSelectionProfileReleaseError, match="unchanged"):
        publish_chongqing_source_selection_profile_change(
            history,
            profile,
            change_reason="no-op",
        )

    banzhu_catalog = build_chongqing_federated_compensation_source_catalog()
    banzhu = build_chongqing_federated_compensation_source_selection_profile(
        banzhu_catalog,
        "banzhu_adjustment",
    )
    with pytest.raises(ChongqingSourceSelectionProfileReleaseError, match="identity"):
        publish_chongqing_source_selection_profile_change(
            history,
            banzhu,
            change_reason="cross-scenario change",
        )

    revised = _revised_profile(tmp_path)
    changed = publish_chongqing_source_selection_profile_change(
        history,
        revised,
        change_reason="customer scenario evidence technical revision",
    )
    with pytest.raises(ChongqingSourceSelectionProfileReleaseError, match="earlier release"):
        rollback_chongqing_source_selection_profile_release(
            changed,
            changed.active_release_sha256,
            revised,
            change_reason="current release is not a rollback target",
        )
    with pytest.raises(ChongqingSourceSelectionProfileReleaseError, match="target release"):
        rollback_chongqing_source_selection_profile_release(
            changed,
            history.active_release_sha256,
            revised,
            change_reason="mismatched rollback content",
        )

    tampered = changed.model_copy(update={"active_release_sha256": "f" * 64})
    with pytest.raises(ValidationError, match="active source-selection profile"):
        ChongqingSourceSelectionProfileReleaseHistory.model_validate(
            tampered.model_dump(mode="python")
        )

    tampered_release = changed.active_release.model_copy(update={"source_catalog_sha256": "e" * 64})
    tampered_release_payload = changed.model_dump(mode="python")
    tampered_releases = list(tampered_release_payload["releases"])
    tampered_releases[-1] = tampered_release.model_dump(mode="python")
    tampered_release_payload["releases"] = tampered_releases
    with pytest.raises(ValidationError, match="release fingerprint"):
        ChongqingSourceSelectionProfileReleaseHistory.model_validate(tampered_release_payload)
