from datetime import UTC, datetime
from uuid import uuid4

import pytest

from data_agent.gis_service_control_plane import (
    GISServiceDefinitionVersion,
    GISServiceSLOBinding,
    service_release_binding_fingerprint,
)
from data_agent.jqdltb_serving_release import (
    build_jqdltb_serving_release_binding,
    jqdltb_serving_release_fingerprint,
)
from data_agent.test_gis_service_control_plane import (
    NOW,
    _definition,
    _mvt_serving_projection,
    _release_bundle,
)


def _binding():
    definition = _definition().model_copy(update={"service_type": "vector_tile"})
    definition = GISServiceDefinitionVersion(
        **definition.model_dump(mode="python", exclude={"definition_sha256"}),
        definition_sha256=__import__(
            "data_agent.gis_service_control_plane", fromlist=["gis_service_definition_fingerprint"]
        ).gis_service_definition_fingerprint(
            definition.model_dump(mode="python", exclude={"definition_sha256"})
        ),
    )
    layer, _, _, release = _release_bundle(definition)
    projection = _mvt_serving_projection(definition, layer)
    release_values = release.model_dump(mode="python", exclude={"binding_sha256"})
    release_values["mvt_serving_projection_version_id"] = (
        projection.mvt_serving_projection_version_id
    )
    from data_agent.gis_service_control_plane import ServiceReleaseBinding

    release = ServiceReleaseBinding(
        **release_values,
        binding_sha256=service_release_binding_fingerprint(release_values),
    )
    slo = GISServiceSLOBinding(
        tenant_id="planning",
        binding_id=uuid4(),
        service_urn=definition.service_urn,
        slo_definition_ref="gda://planning/slo_definition/districts",
        active_version_ref="gda://planning/slo_definition/districts.v1",
        definition_fingerprint="b" * 64,
        approval_case_ref="gda://planning/approval_case/slo-v1",
        activation_version=1,
        bound_by="human:service-owner",
        binding_reason="exact SLO activation",
        bound_at=NOW,
    )
    return build_jqdltb_serving_release_binding(
        tenant_id="planning",
        product_urn=definition.source_product_urn,
        data_product_version_id=definition.source_data_product_version_id,
        manifest_sha256=definition.source_manifest_sha256,
        output_resource_version_id=layer.source_output_resource_version_id,
        service=definition,
        layer=layer,
        projection=projection,
        release=release,
        slo=slo,
        bound_by="workload:serving-controller",
        bound_at=datetime(2026, 8, 26, 4, tzinfo=UTC),
    )


def test_serving_binding_fingerprints_exact_product_and_mvt_chain():
    binding = _binding()
    assert binding.binding_sha256 == jqdltb_serving_release_fingerprint(binding)
    assert binding.service.source_data_product_version_id == binding.data_product_version_id
    assert (
        binding.projection.source_output_resource_version_id
        == binding.output_resource_version_id
    )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("manifest_sha256", "f" * 64, "manifest hash"),
        ("output_resource_version_id", uuid4(), "ADS output"),
        ("data_product_version_id", uuid4(), "DataProductVersion"),
    ),
)
def test_serving_binding_rejects_cross_surface_drift(field, replacement, message):
    binding = _binding()
    with pytest.raises(ValueError, match=message):
        build_jqdltb_serving_release_binding(
            tenant_id=binding.tenant_id,
            product_urn=binding.product_urn,
            data_product_version_id=(
                replacement
                if field == "data_product_version_id"
                else binding.data_product_version_id
            ),
            manifest_sha256=(
                replacement if field == "manifest_sha256" else binding.manifest_sha256
            ),
            output_resource_version_id=(
                replacement
                if field == "output_resource_version_id"
                else binding.output_resource_version_id
            ),
            service=binding.service,
            layer=binding.layer,
            projection=binding.projection,
            release=binding.release,
            slo=binding.slo,
            bound_by=binding.bound_by,
            bound_at=binding.bound_at,
        )
