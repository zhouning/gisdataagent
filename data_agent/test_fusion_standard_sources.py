"""Tests for MMFE standard-source registry helpers."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
import zipfile


class _FakeHttpResponse:
    def __init__(self, body: bytes, *, content_type: str = "text/plain", status: int = 200, url: str = ""):
        self._body = body
        self.headers = {"Content-Type": content_type}
        self.status = status
        self.url = url

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def _write_minimal_docx(path: Path, paragraphs: list[str]) -> None:
    paragraph_xml = "".join(
        (
            "<w:p><w:r><w:t>"
            + text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            + "</w:t></w:r></w:p>"
        )
        for text in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraph_xml}</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)


class TestFusionStandardSources(unittest.TestCase):
    def test_registry_tracks_official_standard_and_local_expert_materials(self):
        from data_agent.fusion.standard_sources import (
            STANDARD_SOURCE_REGISTRY_SCHEMA,
            build_standard_source_registry,
            flatten_standard_source_registry,
        )

        role_contracts = {
            "source_documents": [
                "自然资源“一张图”数据库体系结构（2）统一调查监测1126",
                "GB/T 21010-2017 土地利用现状分类",
            ]
        }

        registry = build_standard_source_registry(
            role_contracts,
            timestamp="2026-06-17T00:00:00+00:00",
        )
        rows = flatten_standard_source_registry(registry)
        by_identifier = {row["standard_identifier"]: row for row in rows}

        self.assertEqual(registry["schema"], STANDARD_SOURCE_REGISTRY_SCHEMA)
        self.assertEqual(registry["source_count"], 2)
        self.assertEqual(registry["summary"]["official_verified_count"], 1)
        self.assertEqual(registry["summary"]["pending_official_source_count"], 1)
        self.assertIn("GB/T 21010-2017", by_identifier)
        gbt21010 = by_identifier["GB/T 21010-2017"]
        self.assertEqual(gbt21010["retrieval_status"], "official_fulltext_available")
        self.assertEqual(gbt21010["access_mode"], "online_preview_and_download")
        self.assertIn("openstd.samr.gov.cn", gbt21010["official_url"])
        self.assertTrue(gbt21010["can_download"])
        self.assertTrue(gbt21010["can_online_preview"])

    def test_unknown_standard_is_kept_as_pending_evidence(self):
        from data_agent.fusion.standard_sources import build_standard_source_registry

        registry = build_standard_source_registry({"source_documents": ["未知标准材料"]})

        self.assertEqual(registry["source_count"], 1)
        self.assertEqual(
            registry["entries"][0]["retrieval_status"],
            "official_source_pending",
        )
        self.assertEqual(registry["summary"]["pending_official_source_count"], 1)

    def test_ingestion_plan_turns_registry_into_auditable_tasks(self):
        from data_agent.fusion.standard_sources import (
            STANDARD_SOURCE_INGESTION_PLAN_SCHEMA,
            build_standard_source_ingestion_plan,
            build_standard_source_registry,
            validate_standard_source_ingestion_plan,
        )

        registry = build_standard_source_registry(
            {
                "source_documents": [
                    "自然资源“一张图”数据库体系结构（2）统一调查监测1126",
                    "GB/T 21010-2017 土地利用现状分类",
                ]
            },
            timestamp="2026-06-17T00:00:00+00:00",
        )
        plan = build_standard_source_ingestion_plan(
            registry,
            timestamp="2026-06-17T00:00:00+00:00",
        )
        validation = validate_standard_source_ingestion_plan(plan)
        by_identifier = {task["standard_identifier"]: task for task in plan["tasks"]}

        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(plan["schema"], STANDARD_SOURCE_INGESTION_PLAN_SCHEMA)
        self.assertFalse(plan["summary"]["ready"])
        self.assertEqual(plan["summary"]["blocked_task_count"], 2)
        self.assertEqual(plan["summary"]["official_source_missing_count"], 1)
        local_task = by_identifier["NR-ONE-MAP-DB-ARCH-02-SURVEY-MONITORING"]
        self.assertIn("find_and_verify_official_source", local_task["required_actions"])
        self.assertIn("official_source_missing", local_task["blocking_reasons"])
        official_task = by_identifier["GB/T 21010-2017"]
        self.assertIn(
            "download_or_archive_fulltext_and_record_checksum",
            official_task["required_actions"],
        )
        self.assertIn(
            "extract_clauses_fields_value_domains_and_citation_anchors",
            official_task["required_actions"],
        )

    def test_ingestion_plan_can_mark_downloaded_extracted_source_ready(self):
        from data_agent.fusion.standard_sources import build_standard_source_ingestion_plan

        registry = {
            "schema": "mmfe.standard_source_registry.v1",
            "entries": [
                {
                    "source_name": "GB/T 21010-2017 土地利用现状分类",
                    "standard_identifier": "GB/T 21010-2017",
                    "title_zh": "土地利用现状分类",
                    "authority": "国家市场监督管理总局 / 国家标准化管理委员会",
                    "official_platform": "国家标准全文公开系统",
                    "official_url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo",
                    "retrieval_status": "downloaded_fulltext",
                    "access_mode": "archived_fulltext",
                    "can_download": True,
                    "checksum_sha256": "abc123",
                    "extraction_status": "extracted",
                    "not_for_production_gap": False,
                }
            ],
        }

        plan = build_standard_source_ingestion_plan(registry)

        self.assertTrue(plan["summary"]["ready"])
        self.assertEqual(plan["summary"]["ready_task_count"], 1)
        self.assertEqual(plan["tasks"][0]["status"], "ready")
        self.assertEqual(plan["tasks"][0]["blocking_reasons"], [])

    def test_ingestion_runner_reports_missing_injected_executors(self):
        from data_agent.fusion.standard_sources import run_standard_source_ingestion_plan

        plan = {
            "schema": "mmfe.standard_source_ingestion_plan.v1",
            "summary": {"ready": False},
            "tasks": [
                {
                    "task_id": "standard-source-ingest-1",
                    "standard_identifier": "GB/T 21010-2017",
                    "official_url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo",
                    "download_required": True,
                    "required_actions": [
                        "download_or_archive_fulltext_and_record_checksum",
                        "extract_clauses_fields_value_domains_and_citation_anchors",
                    ],
                }
            ],
        }

        result = run_standard_source_ingestion_plan(plan, timestamp="2026-06-17T00:00:00+00:00")

        self.assertFalse(result["valid"])
        self.assertEqual(result["schema"], "mmfe.standard_source_ingestion_run.v1")
        self.assertEqual(result["summary"]["failed_task_count"], 1)
        self.assertTrue(
            any("fetcher is required" in message for error in result["errors"] for message in error["errors"])
        )
        self.assertTrue(
            any("extractor is required" in message for error in result["errors"] for message in error["errors"])
        )

    def test_ingestion_runner_records_archive_checksum_and_citation_anchors(self):
        from data_agent.fusion.standard_sources import (
            run_standard_source_ingestion_plan,
            validate_standard_source_ingestion_run,
        )

        plan = {
            "schema": "mmfe.standard_source_ingestion_plan.v1",
            "summary": {"ready": False},
            "tasks": [
                {
                    "task_id": "standard-source-ingest-1",
                    "standard_identifier": "GB/T 21010-2017",
                    "official_url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo",
                    "download_required": True,
                    "required_actions": [
                        "download_or_archive_fulltext_and_record_checksum",
                        "extract_clauses_fields_value_domains_and_citation_anchors",
                    ],
                }
            ],
        }

        def fetcher(task):
            body = b"GB/T 21010-2017 clause text"
            return {"body": body, "bytes_fetched": len(body)}

        def archiver(task, body):
            return {
                "archive_uri": f"s3://standards-archive/{task['standard_identifier']}.pdf",
                "bytes_written": len(body),
            }

        def extractor(task, body, archive):
            return {
                "extraction_status": "extracted",
                "citation_anchor_count": 2,
                "anchors": [
                    {"anchor_id": "gbt21010-1", "citation": "GB/T 21010-2017 §1"},
                    {"anchor_id": "gbt21010-2", "citation": "GB/T 21010-2017 §2"},
                ],
            }

        result = run_standard_source_ingestion_plan(
            plan,
            fetcher=fetcher,
            archiver=archiver,
            extractor=extractor,
            timestamp="2026-06-17T00:00:00+00:00",
        )
        validation = validate_standard_source_ingestion_run(result)

        self.assertTrue(validation["valid"], validation["errors"])
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["summary"]["ingested_task_count"], 1)
        self.assertEqual(result["summary"]["checksum_recorded_count"], 1)
        self.assertEqual(result["summary"]["extracted_task_count"], 1)
        self.assertEqual(result["summary"]["citation_anchor_count"], 2)
        task_result = result["task_results"][0]
        self.assertEqual(task_result["status"], "ingested")
        self.assertEqual(task_result["archive_uri"], "s3://standards-archive/GB/T 21010-2017.pdf")
        self.assertEqual(len(task_result["checksum_sha256"]), 64)

    def test_citation_anchor_sidecar_builder_validates_and_writes_contract(self):
        from data_agent.fusion.standard_sources import (
            STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA,
            build_standard_source_citation_anchor_sidecar,
            validate_standard_source_citation_anchor_sidecar,
            write_standard_source_citation_anchor_sidecar,
        )

        task = {
            "task_id": "standard-source-ingest-1",
            "standard_identifier": "GB/T 21010-2017",
            "source_name": "GB/T 21010-2017 土地利用现状分类",
        }
        sidecar = build_standard_source_citation_anchor_sidecar(
            task,
            anchors=[
                {
                    "anchor_id": "gbt21010-1",
                    "citation": "GB/T 21010-2017 §1",
                    "text": "1 范围",
                }
            ],
            archive_uri="s3://standards-archive/gbt21010.txt",
            checksum_sha256="abc123",
            timestamp="2026-06-17T00:00:00+00:00",
        )

        validation = validate_standard_source_citation_anchor_sidecar(sidecar)
        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(sidecar["schema"], STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA)
        self.assertEqual(sidecar["citation_anchor_count"], 1)
        self.assertEqual(sidecar["anchors"][0]["standard_identifier"], "GB/T 21010-2017")

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "gbt21010.citation_anchors.json"
            written = write_standard_source_citation_anchor_sidecar(sidecar, out_path)
            loaded = json.loads(Path(written).read_text(encoding="utf-8"))

        self.assertEqual(loaded["schema"], STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA)
        self.assertEqual(loaded["anchors"][0]["citation"], "GB/T 21010-2017 §1")

    def test_local_standard_source_adapters_archive_and_write_citation_sidecar(self):
        from data_agent.fusion.standard_sources import (
            STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA,
            build_local_standard_source_archiver,
            build_local_standard_source_extractor,
            build_local_standard_source_fetcher,
            run_standard_source_ingestion_plan,
            validate_standard_source_citation_anchor_sidecar,
            validate_standard_source_ingestion_run,
        )

        plan = {
            "schema": "mmfe.standard_source_ingestion_plan.v1",
            "summary": {"ready": False},
            "tasks": [
                {
                    "task_id": "standard-source-ingest-1",
                    "standard_identifier": "GB/T 21010-2017",
                    "source_name": "GB/T 21010-2017 土地利用现状分类",
                    "official_url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo",
                    "download_required": True,
                    "required_actions": [
                        "download_or_archive_fulltext_and_record_checksum",
                        "extract_clauses_fields_value_domains_and_citation_anchors",
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "GB_T_21010_2017.txt"
            source.write_text(
                "\n".join([
                    "1 范围",
                    "本标准规定了土地利用现状分类的分类体系。",
                    "2 规范性引用文件",
                    "GB/T 相关标准适用于本文件。",
                    "3 术语和定义",
                    "下列术语和定义适用于本文件。",
                ]),
                encoding="utf-8",
            )
            result = run_standard_source_ingestion_plan(
                plan,
                fetcher=build_local_standard_source_fetcher(
                    sources_by_identifier={"GB/T 21010-2017": source}
                ),
                archiver=build_local_standard_source_archiver(
                    tmp_path / "archive",
                    uri_prefix="s3://standards-archive/local",
                ),
                extractor=build_local_standard_source_extractor(tmp_path / "sidecars"),
                timestamp="2026-06-17T00:00:00+00:00",
            )

            validation = validate_standard_source_ingestion_run(result)
            task_result = result["task_results"][0]
            sidecar_path = Path(task_result["extraction_result"]["sidecar_path"])
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

        self.assertTrue(validation["valid"], validation["errors"])
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["summary"]["ingested_task_count"], 1)
        self.assertEqual(result["summary"]["checksum_recorded_count"], 1)
        self.assertEqual(result["summary"]["extracted_task_count"], 1)
        self.assertEqual(task_result["status"], "ingested")
        self.assertTrue(task_result["archive_uri"].startswith("s3://standards-archive/local/"))
        self.assertEqual(len(task_result["checksum_sha256"]), 64)
        self.assertGreaterEqual(task_result["citation_anchor_count"], 3)
        self.assertEqual(sidecar["schema"], STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA)
        self.assertEqual(sidecar["archive_uri"], task_result["archive_uri"])
        self.assertGreaterEqual(sidecar["citation_anchor_count"], 3)
        self.assertTrue(validate_standard_source_citation_anchor_sidecar(sidecar)["valid"])

    def test_local_standard_source_extractor_reports_unsupported_binary_as_failed_task(self):
        from data_agent.fusion.standard_sources import (
            build_local_standard_source_archiver,
            build_local_standard_source_extractor,
            build_local_standard_source_fetcher,
            run_standard_source_ingestion_plan,
        )

        plan = {
            "schema": "mmfe.standard_source_ingestion_plan.v1",
            "summary": {"ready": False},
            "tasks": [
                {
                    "task_id": "standard-source-ingest-1",
                    "standard_identifier": "GB/T 21010-2017",
                    "source_name": "GB/T 21010-2017 土地利用现状分类",
                    "official_url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo",
                    "download_required": True,
                    "required_actions": [
                        "download_or_archive_fulltext_and_record_checksum",
                        "extract_clauses_fields_value_domains_and_citation_anchors",
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "GB_T_21010_2017.pdf"
            source.write_bytes(b"%PDF-1.7\nbinary placeholder\n")
            result = run_standard_source_ingestion_plan(
                plan,
                fetcher=build_local_standard_source_fetcher(
                    sources_by_identifier={"GB/T 21010-2017": source}
                ),
                archiver=build_local_standard_source_archiver(tmp_path / "archive"),
                extractor=build_local_standard_source_extractor(tmp_path / "sidecars"),
                timestamp="2026-06-17T00:00:00+00:00",
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["summary"]["failed_task_count"], 1)
        self.assertEqual(
            result["task_results"][0]["extraction_status"],
            "unsupported_fulltext_format",
        )
        self.assertTrue(
            any(
                "unsupported_fulltext_format" in message
                for error in result["errors"]
                for message in error["errors"]
            )
        )

    def test_local_standard_source_extractor_reads_docx_with_stdlib_and_writes_sidecar(self):
        from data_agent.fusion.standard_sources import (
            STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA,
            build_local_standard_source_archiver,
            build_local_standard_source_extractor,
            build_local_standard_source_fetcher,
            run_standard_source_ingestion_plan,
        )

        plan = {
            "schema": "mmfe.standard_source_ingestion_plan.v1",
            "summary": {"ready": False},
            "tasks": [
                {
                    "task_id": "standard-source-ingest-1",
                    "standard_identifier": "NR-ONE-MAP-DB-ARCH-02-SURVEY-MONITORING",
                    "source_name": "自然资源一张图数据库体系结构",
                    "official_url": "https://example.gov.cn/standard.docx",
                    "download_required": True,
                    "required_actions": [
                        "download_or_archive_fulltext_and_record_checksum",
                        "extract_clauses_fields_value_domains_and_citation_anchors",
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "one_map_arch.docx"
            _write_minimal_docx(
                source,
                [
                    "1 范围",
                    "本文件规定了自然资源一张图数据库体系结构。",
                    "2 术语和定义",
                    "下列术语和定义适用于本文件。",
                    "3 数据分层",
                    "统一调查监测数据应按主题组织。",
                ],
            )
            result = run_standard_source_ingestion_plan(
                plan,
                fetcher=build_local_standard_source_fetcher(
                    sources_by_identifier={"NR-ONE-MAP-DB-ARCH-02-SURVEY-MONITORING": source}
                ),
                archiver=build_local_standard_source_archiver(tmp_path / "archive"),
                extractor=build_local_standard_source_extractor(tmp_path / "sidecars"),
                timestamp="2026-06-17T00:00:00+00:00",
            )
            task_result = result["task_results"][0]
            sidecar = json.loads(Path(task_result["extraction_result"]["sidecar_path"]).read_text(encoding="utf-8"))

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(task_result["extraction_status"], "extracted")
        self.assertEqual(task_result["citation_anchor_count"], 6)
        self.assertEqual(sidecar["schema"], STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA)
        self.assertEqual(sidecar["citation_anchor_count"], 6)
        self.assertIn("1 范围", sidecar["anchors"][0]["text"])

    def test_apply_ingestion_run_updates_registry_and_makes_next_plan_ready(self):
        from data_agent.fusion.standard_sources import (
            apply_standard_source_ingestion_run,
            build_local_standard_source_archiver,
            build_local_standard_source_extractor,
            build_local_standard_source_fetcher,
            build_standard_source_ingestion_plan,
            run_standard_source_ingestion_plan,
        )

        registry = {
            "schema": "mmfe.standard_source_registry.v1",
            "entries": [
                {
                    "source_name": "GB/T 21010-2017 土地利用现状分类",
                    "standard_identifier": "GB/T 21010-2017",
                    "title_zh": "土地利用现状分类",
                    "authority": "国家市场监督管理总局 / 国家标准化管理委员会",
                    "official_platform": "国家标准全文公开系统",
                    "official_url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo",
                    "retrieval_status": "official_fulltext_available",
                    "access_mode": "online_preview_and_download",
                    "can_download": True,
                    "not_for_production_gap": False,
                }
            ],
        }
        plan = build_standard_source_ingestion_plan(registry)
        self.assertFalse(plan["summary"]["ready"])

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "GB_T_21010_2017.txt"
            source.write_text("1 范围\n2 术语和定义\n3 分类体系\n", encoding="utf-8")
            run = run_standard_source_ingestion_plan(
                plan,
                fetcher=build_local_standard_source_fetcher(
                    sources_by_identifier={"GB/T 21010-2017": source}
                ),
                archiver=build_local_standard_source_archiver(tmp_path / "archive"),
                extractor=build_local_standard_source_extractor(tmp_path / "sidecars"),
                timestamp="2026-06-17T00:00:00+00:00",
            )
            updated = apply_standard_source_ingestion_run(
                registry,
                run,
                timestamp="2026-06-17T01:00:00+00:00",
            )

        entry = updated["entries"][0]
        next_plan = build_standard_source_ingestion_plan(updated)

        self.assertEqual(updated["updated_at"], "2026-06-17T01:00:00+00:00")
        self.assertEqual(entry["retrieval_status"], "downloaded_fulltext")
        self.assertEqual(entry["access_mode"], "archived_fulltext")
        self.assertEqual(entry["retrieval_method"], "mmfe_standard_source_ingestion_run")
        self.assertTrue(entry["archive_uri"].startswith("file://"))
        self.assertEqual(len(entry["checksum_sha256"]), 64)
        self.assertEqual(entry["extraction_status"], "extracted")
        self.assertEqual(entry["citation_anchor_count"], 3)
        self.assertEqual(entry["clause_anchor_count"], 3)
        self.assertTrue(entry["citation_anchor_sidecar_path"].endswith(".citation_anchors.json"))
        self.assertEqual(updated["last_ingestion_run"]["summary"]["ingested_task_count"], 1)
        self.assertTrue(next_plan["summary"]["ready"], next_plan)
        self.assertEqual(next_plan["tasks"][0]["status"], "ready")
        self.assertEqual(next_plan["tasks"][0]["blocking_reasons"], [])

    def test_apply_ingestion_run_ignores_failed_task_results(self):
        from data_agent.fusion.standard_sources import apply_standard_source_ingestion_run

        registry = {
            "schema": "mmfe.standard_source_registry.v1",
            "entries": [
                {
                    "source_name": "GB/T 21010-2017 土地利用现状分类",
                    "standard_identifier": "GB/T 21010-2017",
                    "retrieval_status": "official_fulltext_available",
                    "access_mode": "online_preview_and_download",
                }
            ],
        }
        run = {
            "schema": "mmfe.standard_source_ingestion_run.v1",
            "valid": False,
            "errors": [{"task_id": "standard-source-ingest-1", "errors": ["extractor failed"]}],
            "summary": {"failed_task_count": 1},
            "task_results": [
                {
                    "task_id": "standard-source-ingest-1",
                    "standard_identifier": "GB/T 21010-2017",
                    "valid": False,
                    "status": "error",
                    "archive_uri": "s3://standards-archive/bad.pdf",
                    "checksum_sha256": "bad",
                    "extraction_status": "unsupported_fulltext_format",
                    "citation_anchor_count": 0,
                }
            ],
        }

        updated = apply_standard_source_ingestion_run(registry, run)

        self.assertEqual(updated["entries"][0]["retrieval_status"], "official_fulltext_available")
        self.assertEqual(updated["entries"][0]["access_mode"], "online_preview_and_download")
        self.assertNotIn("archive_uri", updated["entries"][0])

    def test_http_standard_source_fetcher_reads_allowed_official_url_without_real_network(self):
        from data_agent.fusion.standard_sources import build_http_standard_source_fetcher

        calls = []
        body = "1 范围\n2 术语和定义\n".encode("utf-8")

        def opener(request, timeout):
            calls.append({"request": request, "timeout": timeout})
            return _FakeHttpResponse(
                body,
                content_type="text/plain; charset=utf-8",
                status=200,
                url=request.full_url,
            )

        fetcher = build_http_standard_source_fetcher(
            allowed_domains=["openstd.samr.gov.cn"],
            timeout_seconds=3.5,
            user_agent="mmfe-test-agent",
            opener=opener,
        )
        result = fetcher({
            "official_url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=abc",
            "standard_identifier": "GB/T 21010-2017",
        })

        self.assertEqual(calls[0]["timeout"], 3.5)
        self.assertEqual(calls[0]["request"].headers["User-agent"], "mmfe-test-agent")
        self.assertEqual(result["body"], body)
        self.assertEqual(result["bytes_fetched"], len(body))
        self.assertEqual(result["content_type"], "text/plain")
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["source_url"], "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=abc")
        self.assertEqual(result["sha256"], hashlib.sha256(body).hexdigest())

    def test_http_standard_source_fetcher_rejects_unlisted_domain_before_network(self):
        from data_agent.fusion.standard_sources import build_http_standard_source_fetcher

        called = False

        def opener(request, timeout):
            nonlocal called
            called = True
            return _FakeHttpResponse(b"")

        fetcher = build_http_standard_source_fetcher(
            allowed_domains=["openstd.samr.gov.cn"],
            opener=opener,
        )

        with self.assertRaisesRegex(ValueError, "not allowed"):
            fetcher({"official_url": "https://example.com/standard.pdf"})
        self.assertFalse(called)

    def test_s3_standard_source_archiver_uploads_bytes_and_returns_archive_metadata(self):
        from data_agent.fusion.standard_sources import archive_standard_source_bytes_to_s3

        calls = []

        class FakeS3Client:
            def put_object(self, **kwargs):
                calls.append(kwargs)

        class FakeBoto3(types.SimpleNamespace):
            def client(self, service, **kwargs):
                self.client_call = {"service": service, "kwargs": kwargs}
                return FakeS3Client()

        fake_boto3 = FakeBoto3()
        fake_botocore = types.ModuleType("botocore")
        fake_config_module = types.ModuleType("botocore.config")

        class FakeBotoConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_config_module.Config = FakeBotoConfig
        body = b"1 scope\n2 terms\n"
        task = {
            "standard_identifier": "GB/T 21010-2017",
            "source_path": "GB_T_21010_2017.txt",
            "content_type": "text/plain",
        }

        with mock.patch.dict(
            sys.modules,
            {
                "boto3": fake_boto3,
                "botocore": fake_botocore,
                "botocore.config": fake_config_module,
            },
        ):
            result = archive_standard_source_bytes_to_s3(
                task,
                body,
                target_uri_prefix="s3://standards-archive/mmfe/official",
                endpoint_url="http://minio:9000",
                access_key_id="minio_admin",
                secret_access_key="local_dev_minio_secret",
            )

        self.assertEqual(fake_boto3.client_call["service"], "s3")
        self.assertEqual(fake_boto3.client_call["kwargs"]["endpoint_url"], "http://minio:9000")
        self.assertEqual(calls[0]["Bucket"], "standards-archive")
        self.assertTrue(calls[0]["Key"].startswith("mmfe/official/gb-t-21010-2017-"))
        self.assertTrue(calls[0]["Key"].endswith(".txt"))
        self.assertEqual(calls[0]["Body"], body)
        self.assertEqual(calls[0]["ContentType"], "text/plain")
        self.assertEqual(result["archive_uri"], f"s3://standards-archive/{calls[0]['Key']}")
        self.assertEqual(result["bytes_written"], len(body))
        self.assertEqual(result["sha256"], hashlib.sha256(body).hexdigest())

    def test_s3_standard_source_archiver_integrates_with_ingestion_runner(self):
        from data_agent.fusion.standard_sources import (
            build_local_standard_source_extractor,
            build_local_standard_source_fetcher,
            build_s3_standard_source_archiver,
            run_standard_source_ingestion_plan,
        )

        calls = []

        class FakeS3Client:
            def put_object(self, **kwargs):
                calls.append(kwargs)

        class FakeBoto3(types.SimpleNamespace):
            def client(self, service, **kwargs):
                self.client_call = {"service": service, "kwargs": kwargs}
                return FakeS3Client()

        fake_boto3 = FakeBoto3()
        fake_botocore = types.ModuleType("botocore")
        fake_config_module = types.ModuleType("botocore.config")

        class FakeBotoConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_config_module.Config = FakeBotoConfig
        plan = {
            "schema": "mmfe.standard_source_ingestion_plan.v1",
            "summary": {"ready": False},
            "tasks": [
                {
                    "task_id": "standard-source-ingest-1",
                    "standard_identifier": "GB/T 21010-2017",
                    "source_name": "GB/T 21010-2017 土地利用现状分类",
                    "official_url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo",
                    "download_required": True,
                    "required_actions": [
                        "download_or_archive_fulltext_and_record_checksum",
                        "extract_clauses_fields_value_domains_and_citation_anchors",
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "GB_T_21010_2017.txt"
            source.write_text("1 范围\n2 术语和定义\n3 分类体系\n", encoding="utf-8")
            with mock.patch.dict(
                sys.modules,
                {
                    "boto3": fake_boto3,
                    "botocore": fake_botocore,
                    "botocore.config": fake_config_module,
                },
            ):
                result = run_standard_source_ingestion_plan(
                    plan,
                    fetcher=build_local_standard_source_fetcher(
                        sources_by_identifier={"GB/T 21010-2017": source}
                    ),
                    archiver=build_s3_standard_source_archiver(
                        target_uri_prefix="s3://standards-archive/mmfe/official",
                        endpoint_url="http://minio:9000",
                    ),
                    extractor=build_local_standard_source_extractor(tmp_path / "sidecars"),
                    timestamp="2026-06-17T00:00:00+00:00",
                )

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["summary"]["ingested_task_count"], 1)
        self.assertEqual(result["summary"]["checksum_recorded_count"], 1)
        self.assertEqual(result["summary"]["extracted_task_count"], 1)
        self.assertEqual(len(calls), 1)
        task_result = result["task_results"][0]
        self.assertTrue(task_result["archive_uri"].startswith("s3://standards-archive/mmfe/official/"))
        self.assertEqual(task_result["bytes_archived"], calls[0]["ContentLength"] if "ContentLength" in calls[0] else len(calls[0]["Body"]))
        self.assertGreaterEqual(task_result["citation_anchor_count"], 3)

    def test_http_fetcher_s3_archiver_and_extractor_run_as_injected_ingestion_path(self):
        from data_agent.fusion.standard_sources import (
            build_http_standard_source_fetcher,
            build_local_standard_source_extractor,
            build_s3_standard_source_archiver,
            run_standard_source_ingestion_plan,
        )

        http_calls = []
        s3_calls = []
        body = "1 范围\n2 术语和定义\n3 分类体系\n".encode("utf-8")

        def opener(request, timeout):
            http_calls.append({"request": request, "timeout": timeout})
            return _FakeHttpResponse(body, content_type="text/plain", status=200, url=request.full_url)

        class FakeS3Client:
            def put_object(self, **kwargs):
                s3_calls.append(kwargs)

        class FakeBoto3(types.SimpleNamespace):
            def client(self, service, **kwargs):
                self.client_call = {"service": service, "kwargs": kwargs}
                return FakeS3Client()

        fake_boto3 = FakeBoto3()
        fake_botocore = types.ModuleType("botocore")
        fake_config_module = types.ModuleType("botocore.config")

        class FakeBotoConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_config_module.Config = FakeBotoConfig
        plan = {
            "schema": "mmfe.standard_source_ingestion_plan.v1",
            "summary": {"ready": False},
            "tasks": [
                {
                    "task_id": "standard-source-ingest-1",
                    "standard_identifier": "GB/T 21010-2017",
                    "source_name": "GB/T 21010-2017 土地利用现状分类",
                    "official_url": "https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=abc",
                    "download_required": True,
                    "required_actions": [
                        "download_or_archive_fulltext_and_record_checksum",
                        "extract_clauses_fields_value_domains_and_citation_anchors",
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                sys.modules,
                {
                    "boto3": fake_boto3,
                    "botocore": fake_botocore,
                    "botocore.config": fake_config_module,
                },
            ):
                result = run_standard_source_ingestion_plan(
                    plan,
                    fetcher=build_http_standard_source_fetcher(
                        allowed_domains=["openstd.samr.gov.cn"],
                        opener=opener,
                    ),
                    archiver=build_s3_standard_source_archiver(
                        target_uri_prefix="s3://standards-archive/mmfe/official",
                    ),
                    extractor=build_local_standard_source_extractor(Path(tmp) / "sidecars"),
                    timestamp="2026-06-17T00:00:00+00:00",
                )

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(len(http_calls), 1)
        self.assertEqual(len(s3_calls), 1)
        self.assertEqual(result["summary"]["ingested_task_count"], 1)
        self.assertEqual(result["summary"]["extracted_task_count"], 1)
        task_result = result["task_results"][0]
        self.assertTrue(task_result["archive_uri"].startswith("s3://standards-archive/mmfe/official/"))
        self.assertEqual(task_result["bytes_fetched"], len(body))
        self.assertEqual(task_result["bytes_archived"], len(body))
        self.assertGreaterEqual(task_result["citation_anchor_count"], 3)

    def test_ingestion_runner_is_exported_through_fusion_engine_proxy(self):
        from data_agent import fusion_engine

        self.assertEqual(
            fusion_engine.STANDARD_SOURCE_CITATION_ANCHORS_SCHEMA,
            "mmfe.standard_source_citation_anchors.v1",
        )
        self.assertEqual(
            fusion_engine.STANDARD_SOURCE_INGESTION_RUN_SCHEMA,
            "mmfe.standard_source_ingestion_run.v1",
        )
        self.assertTrue(callable(fusion_engine.archive_standard_source_bytes_to_s3))
        self.assertTrue(callable(fusion_engine.apply_standard_source_ingestion_run))
        self.assertTrue(callable(fusion_engine.build_http_standard_source_fetcher))
        self.assertTrue(callable(fusion_engine.build_local_standard_source_fetcher))
        self.assertTrue(callable(fusion_engine.build_local_standard_source_archiver))
        self.assertTrue(callable(fusion_engine.build_local_standard_source_extractor))
        self.assertTrue(callable(fusion_engine.build_s3_standard_source_archiver))
        self.assertTrue(callable(fusion_engine.run_standard_source_ingestion_plan))


if __name__ == "__main__":
    unittest.main()
