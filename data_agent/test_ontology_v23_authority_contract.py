import gzip
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "data_agent/ontology/packages/natural_resource_one_map/2.3.0"
MIGRATION = ROOT / "data_agent/migrations/144_ontology_attachment_field_catalog_source.sql"


def test_v23_package_source_kinds_are_admitted_by_the_authority_schema():
    with gzip.open(PACKAGE / "sources.jsonl.gz", "rt", encoding="utf-8") as stream:
        source_kinds = {json.loads(line)["source_kind"] for line in stream if line.strip()}

    migration = MIGRATION.read_text(encoding="utf-8")
    for source_kind in source_kinds:
        assert f"'{source_kind}'" in migration
    assert "VALIDATE CONSTRAINT ck_gda_ontology_source_kind" in migration
