"""Tests for MMFE production-readiness metadata contracts."""

import unittest


def _manifest() -> dict:
    return {
        "product_type": "semantic_fusion_product",
        "product_id": "sfp-production-readiness-test",
        "sources": [{"path": "s3://lake/raw/pbf.parquet", "data_type": "vector"}],
    }


def _authoritative_source() -> dict:
    return {
        "source_id": "pbf-2026",
        "role": "permanent_basic_farmland",
        "source_path": "s3://lake/raw/pbf/2026/data.parquet",
        "authority": "自然资源主管部门",
        "authority_level": "department",
        "license": "authorized_government_use",
        "access_rights": "authorized",
        "update_date": "2026-06-01",
        "lineage": "official cadastral and permanent-basic-farmland release",
        "crs": "EPSG:4490",
        "scale_or_resolution": "1:10000",
        "official_standard_version": "NR_ONE_MAP_TWM_CORE_2026",
        "security_classification": "internal",
    }


def _ready_standard_source_registry() -> dict:
    return {
        "schema": "mmfe.standard_source_registry.v1",
        "entries": [
            {
                "source_name": "GB/T 21010-2017 土地利用现状分类",
                "standard_identifier": "GB/T 21010-2017",
                "authority": "国家市场监督管理总局 / 国家标准化管理委员会",
                "official_platform": "国家标准全文公开系统",
                "official_url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo",
                "publication_date": "2017-11-01",
                "implementation_date": "2017-11-01",
                "retrieval_status": "downloaded_fulltext",
                "access_mode": "archived_fulltext",
                "archive_uri": "s3://standards-archive/mmfe/gbt21010.pdf",
                "checksum_sha256": "a" * 64,
                "extraction_status": "extracted",
                "citation_anchor_count": 3,
                "not_for_production_gap": False,
            }
        ],
    }


def _authoritative_metadata_record() -> dict:
    return {
        "data_id": "META-pbf-2026",
        "resource_id": "nr:pbf:2026",
        "layer_name": "permanent_basic_farmland",
        "path": "s3://lake/raw/pbf/2026/data.parquet",
        "producer": "重庆市规划和自然资源局",
        "pro_unit_name": "重庆市规划和自然资源局",
        "source_type": "自然资源主管部门正式发布",
        "share_type": "授权共享",
        "update_date": "20260601",
        "receive_batch": "202606",
        "projection": "4490",
        "coordinate_unit": "1:10000",
        "standard_version": "NR_ONE_MAP_TWM_CORE_2026",
        "security_order": "内部",
        "synthetic": False,
        "not_for_production": False,
    }


class TestProductionReadiness(unittest.TestCase):
    def test_authoritative_source_metadata_passes_contract(self):
        from data_agent.fusion.production_readiness import (
            PRODUCTION_READINESS_SCHEMA,
            build_production_readiness_contract,
            validate_production_readiness_contract,
        )

        contract = build_production_readiness_contract(
            _manifest(),
            sources=[_authoritative_source()],
            timestamp="2026-06-17T00:00:00+00:00",
        )
        validation = validate_production_readiness_contract(contract)

        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(contract["schema"], PRODUCTION_READINESS_SCHEMA)
        self.assertTrue(contract["summary"]["production_metadata_ready"])
        self.assertEqual(contract["summary"]["ready_source_count"], 1)
        self.assertEqual(contract["findings"][0]["status"], "pass")

    def test_missing_or_synthetic_source_metadata_blocks_contract(self):
        from data_agent.fusion.production_readiness import build_production_readiness_contract

        contract = build_production_readiness_contract(
            _manifest(),
            sources=[
                {
                    "source_id": "synthetic-pbf",
                    "role": "permanent_basic_farmland",
                    "source_path": "synthetic_pbf.geojson",
                    "synthetic": True,
                    "not_for_production": True,
                }
            ],
            timestamp="2026-06-17T00:00:00+00:00",
        )

        self.assertFalse(contract["summary"]["production_metadata_ready"])
        self.assertEqual(contract["summary"]["blocked_source_count"], 1)
        self.assertGreater(contract["summary"]["missing_field_count"], 0)
        finding = contract["findings"][0]
        self.assertEqual(finding["status"], "fail")
        self.assertIn("authority", finding["missing_fields"])
        self.assertIn("synthetic", finding["invalid_fields"])
        self.assertIn("not_for_production", finding["invalid_fields"])

    def test_explicit_empty_source_list_does_not_fallback_to_manifest_sources(self):
        from data_agent.fusion.production_readiness import build_production_readiness_contract

        contract = build_production_readiness_contract(
            _manifest(),
            sources=[],
            timestamp="2026-06-17T00:00:00+00:00",
        )

        self.assertFalse(contract["summary"]["production_metadata_ready"])
        self.assertEqual(contract["summary"]["source_count"], 0)
        self.assertEqual(contract["findings"], [])

    def test_contract_can_be_loaded_from_manifest_bundle(self):
        from data_agent.fusion.production_readiness import production_readiness_from_manifest

        manifest = _manifest()
        manifest["mmfe_bundle"] = {
            "source_production_metadata": [_authoritative_source()],
        }

        contract = production_readiness_from_manifest(manifest)

        self.assertTrue(contract["summary"]["production_metadata_ready"])
        self.assertEqual(contract["product_id"], "sfp-production-readiness-test")

    def test_contract_can_be_derived_from_manifest_standard_source_registry(self):
        from data_agent.fusion.production_readiness import production_readiness_from_manifest

        manifest = _manifest()
        manifest["sources"] = [{"path": "legacy-fallback.geojson", "data_type": "vector"}]
        manifest["mmfe_bundle"] = {
            "source_production_metadata": [_authoritative_source()],
            "standard_source_registry": _ready_standard_source_registry(),
        }

        contract = production_readiness_from_manifest(manifest)

        self.assertTrue(contract["summary"]["production_metadata_ready"])
        self.assertEqual(contract["summary"]["source_count"], 2)
        self.assertEqual(contract["summary"]["ready_source_count"], 2)
        self.assertEqual(
            [source["source_id"] for source in contract["sources"]],
            ["pbf-2026", "standard-source:GB/T 21010-2017"],
        )

    def test_manifest_standard_source_registry_deduplicates_explicit_rows(self):
        from data_agent.fusion.production_readiness import (
            production_readiness_from_manifest,
            standard_source_production_metadata_from_registry,
        )

        registry = _ready_standard_source_registry()
        manifest = _manifest()
        manifest["mmfe_bundle"] = {
            "source_production_metadata": standard_source_production_metadata_from_registry(registry),
            "standard_source_registry": registry,
        }

        contract = production_readiness_from_manifest(manifest)

        self.assertTrue(contract["summary"]["production_metadata_ready"])
        self.assertEqual(contract["summary"]["source_count"], 1)
        self.assertEqual(contract["sources"][0]["source_id"], "standard-source:GB/T 21010-2017")

    def test_source_metadata_records_map_to_production_metadata(self):
        from data_agent.fusion.production_readiness import (
            build_production_readiness_contract,
            source_production_metadata_from_records,
        )

        rows = source_production_metadata_from_records(
            [_authoritative_metadata_record()],
            defaults={
                "license": "authorized_government_use",
                "access_rights": "authorized",
            },
        )
        row = rows[0]

        self.assertEqual(row["source_id"], "nr:pbf:2026")
        self.assertEqual(row["role"], "permanent_basic_farmland")
        self.assertEqual(row["source_path"], "s3://lake/raw/pbf/2026/data.parquet")
        self.assertEqual(row["authority"], "重庆市规划和自然资源局")
        self.assertEqual(row["authority_level"], "department")
        self.assertEqual(row["update_date"], "2026-06-01")
        self.assertEqual(row["crs"], "EPSG:4490")
        self.assertEqual(row["security_classification"], "internal")
        self.assertFalse(row["synthetic"])
        self.assertFalse(row["not_for_production"])

        contract = build_production_readiness_contract(_manifest(), sources=rows)

        self.assertTrue(contract["summary"]["production_metadata_ready"])
        self.assertEqual(contract["findings"][0]["status"], "pass")

    def test_source_metadata_records_preserve_synthetic_production_block(self):
        from data_agent.fusion.production_readiness import (
            build_production_readiness_contract,
            source_production_metadata_from_records,
        )

        record = dict(_authoritative_metadata_record())
        record.update({
            "resource_id": "synthetic:pbf",
            "synthetic": True,
            "not_for_production": True,
        })

        rows = source_production_metadata_from_records(
            [record],
            defaults={
                "license": "authorized_government_use",
                "access_rights": "authorized",
            },
        )
        contract = build_production_readiness_contract(_manifest(), sources=rows)

        self.assertTrue(rows[0]["not_for_production"])
        self.assertFalse(contract["summary"]["production_metadata_ready"])
        self.assertIn("synthetic", contract["findings"][0]["invalid_fields"])
        self.assertIn("not_for_production", contract["findings"][0]["invalid_fields"])

    def test_manifest_source_metadata_records_are_auto_loaded(self):
        from data_agent.fusion.production_readiness import production_readiness_from_manifest

        manifest = _manifest()
        manifest["mmfe_bundle"] = {
            "source_metadata_records": [_authoritative_metadata_record()],
        }

        contract = production_readiness_from_manifest(manifest)

        self.assertTrue(contract["summary"]["production_metadata_ready"])
        self.assertEqual(contract["summary"]["source_count"], 1)
        self.assertEqual(contract["sources"][0]["source_id"], "nr:pbf:2026")

    def test_standard_source_registry_maps_to_ready_production_metadata(self):
        from data_agent.fusion.production_readiness import (
            build_production_readiness_contract,
            standard_source_production_metadata_from_registry,
        )

        registry = _ready_standard_source_registry()

        rows = standard_source_production_metadata_from_registry(registry)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["source_id"], "standard-source:GB/T 21010-2017")
        self.assertEqual(row["role"], "standard_source")
        self.assertEqual(row["source_path"], "s3://standards-archive/mmfe/gbt21010.pdf")
        self.assertEqual(row["authority_level"], "official_platform")
        self.assertEqual(row["access_rights"], "open")
        self.assertEqual(row["security_classification"], "public")
        self.assertFalse(row["not_for_production"])

        contract = build_production_readiness_contract(
            _manifest(),
            sources=rows,
            timestamp="2026-06-17T00:00:00+00:00",
        )

        self.assertTrue(contract["summary"]["production_metadata_ready"])
        self.assertEqual(contract["summary"]["ready_source_count"], 1)
        self.assertEqual(contract["findings"][0]["status"], "pass")

    def test_standard_source_registry_without_archive_or_extraction_is_blocked(self):
        from data_agent.fusion.production_readiness import (
            build_production_readiness_contract,
            standard_source_production_metadata_from_registry,
        )

        registry = {
            "schema": "mmfe.standard_source_registry.v1",
            "entries": [
                {
                    "source_name": "专家材料包",
                    "standard_identifier": "NR-LOCAL-EXPERT-MATERIAL",
                    "authority": "自然资源专家组",
                    "official_platform": "",
                    "official_url": "",
                    "publication_date": "2026-06-01",
                    "retrieval_status": "local_expert_material_available",
                    "access_mode": "local_expert_material",
                    "not_for_production_gap": True,
                }
            ],
        }

        rows = standard_source_production_metadata_from_registry(registry)
        contract = build_production_readiness_contract(
            _manifest(),
            sources=rows,
            timestamp="2026-06-17T00:00:00+00:00",
        )

        self.assertTrue(rows[0]["not_for_production"])
        self.assertFalse(contract["summary"]["production_metadata_ready"])
        self.assertEqual(contract["summary"]["blocked_source_count"], 1)
        self.assertIn("not_for_production", contract["findings"][0]["invalid_fields"])

    def test_api_is_exported_through_fusion_engine_proxy(self):
        from data_agent import fusion_engine

        self.assertEqual(fusion_engine.PRODUCTION_READINESS_SCHEMA, "mmfe.production_readiness.v1")
        contract = fusion_engine.build_production_readiness_contract(
            _manifest(),
            sources=[_authoritative_source()],
        )
        self.assertTrue(contract["summary"]["production_metadata_ready"])
        self.assertTrue(hasattr(fusion_engine, "standard_source_production_metadata_from_registry"))
        self.assertTrue(hasattr(fusion_engine, "source_production_metadata_from_records"))


if __name__ == "__main__":
    unittest.main()
