from uuid import UUID

import pytest

from data_agent.dolphinscheduler_adapter import compile_dolphinscheduler_workflow
from data_agent.spatial_anonymization_dolphinscheduler import (
    build_spatial_anonymization_definition,
    spatial_anonymization_raw_script,
)

DEFINITION_ID = UUID("72000000-0000-4000-8000-000000000001")


def _definition():
    return build_spatial_anonymization_definition(
        tenant_id="tenant-a",
        definition_urn="gda://tenant-a/definition/spatial-anonymization-v1",
        definition_version_id=DEFINITION_ID,
        task_code=123456789,
        worker_group="gda_dataops_sandbox",
        executor_base_url="http://host.docker.internal:18091",
    )


def test_definition_compiles_without_copying_business_parameters():
    definition = _definition()
    compiled = compile_dolphinscheduler_workflow(definition)
    raw_script = compiled.task_definitions[0]["taskParams"]["rawScript"]

    assert '${gda_tenant_id}' in raw_script
    assert '${gda_run_id}' in raw_script
    for forbidden in (
        "source_schema",
        "source_table",
        "output_table",
        "k_anonymity",
        "dp_epsilon",
        "keep_attrs",
    ):
        assert forbidden not in raw_script
    assert definition.input_contract["anonymization_request"][
        "runtime_parameters"
    ] == ["gda_tenant_id", "gda_run_id"]
    assert compiled.definition_version_id == DEFINITION_ID


def test_executor_origin_rejects_credentials_paths_and_queries():
    for value in (
        "http://user:password@host:8091",
        "http://host:8091/path",
        "http://host:8091?token=secret",
    ):
        with pytest.raises(ValueError, match="origin without credentials"):
            spatial_anonymization_raw_script(value)
