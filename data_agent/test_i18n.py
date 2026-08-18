"""Tests for the GIS Data Agent i18n infrastructure.

Covers: t() function, language switching, fallback, interpolation,
locale normalization, async isolation, key parity, and localized previews.
"""

import asyncio
import re
from pathlib import Path
from string import Formatter

import pytest
import yaml
from data_agent.i18n import (
    HttpLocaleMiddleware,
    _load_translations,
    _translations,
    get_language,
    normalize_language,
    resolve_language,
    resolve_http_language,
    set_language,
    t,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(autouse=True)
def reset_language():
    """Ensure each test starts with default language (zh)."""
    set_language("zh")
    yield
    set_language("zh")


# ===================================================================
# Basic t() behavior
# ===================================================================

class TestDefaultLanguage:
    def test_default_is_zh(self):
        assert get_language() == "zh"

    def test_returns_chinese_by_default(self):
        val = t("action.confirm")
        assert val == "确认执行"

    def test_preview_title_zh(self):
        val = t("preview.title")
        assert "数据预览" in val


class TestSwitchToEnglish:
    def test_switch_and_get(self):
        set_language("en")
        assert get_language() == "en"

    def test_returns_english(self):
        set_language("en")
        val = t("action.confirm")
        assert val == "Confirm"

    def test_preview_title_en(self):
        set_language("en")
        val = t("preview.title")
        assert "Data Preview" in val


class TestArabic:
    def test_locale_alias_is_normalized(self):
        set_language("ar-AE")
        assert get_language() == "ar"

    def test_returns_arabic(self):
        set_language("ar")
        assert t("action.confirm") == "تأكيد التنفيذ"

    def test_preview_title_ar(self):
        set_language("ar_AE")
        assert "معاينة البيانات" in t("preview.title")


class TestLocaleResolution:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("zh-CN", "zh"),
            ("en_US", "en"),
            ("ar-AE", "ar"),
            ("AR", "ar"),
            ("fr-FR", "zh"),
            (None, "zh"),
        ],
    )
    def test_normalize_language(self, value, expected):
        assert normalize_language(value) == expected

    def test_message_metadata_has_precedence(self):
        assert resolve_language(
            user_env={"locale": "en-US"},
            message_metadata={"locale": "ar-AE"},
        ) == "ar"

    def test_user_environment_used_without_message_override(self):
        assert resolve_language(user_env={"locale": "en-US"}) == "en"

    def test_context_is_isolated_between_async_tasks(self):
        async def translate(language: str) -> tuple[str, str]:
            set_language(language)
            await asyncio.sleep(0)
            return get_language(), t("action.confirm")

        async def run():
            return await asyncio.gather(translate("en-US"), translate("ar-AE"))

        assert asyncio.run(run()) == [
            ("en", "Confirm"),
            ("ar", "تأكيد التنفيذ"),
        ]

    def test_http_locale_precedence_and_accept_language_parsing(self):
        assert resolve_http_language("ar-AE", "en-US", "zh-CN") == "ar"
        assert resolve_http_language(None, "en-US", "ar-AE") == "en"
        assert resolve_http_language(None, None, "ar-AE,ar;q=0.9,en;q=0.8") == "ar"
        assert resolve_http_language(None, None, "fr-FR,fr;q=0.9") == "zh"

    def test_http_locale_skips_unsupported_and_zero_weight_languages(self):
        assert resolve_http_language("fr-FR", "en-US", "ar-AE") == "en"
        assert resolve_http_language(
            None,
            None,
            "fr-FR, ar-AE;q=0.8, en-US;q=0.9",
        ) == "en"
        assert resolve_http_language(None, None, "en-US;q=0, ar-AE;q=0.8") == "ar"

    def test_http_locale_uses_app_cookie_before_browser_language(self):
        assert resolve_http_language(
            None,
            None,
            "en-US,en;q=0.9",
            cookie_locale="ar-AE",
        ) == "ar"

    def test_http_middleware_binds_and_resets_language_context(self):
        observed = []
        messages = []

        async def downstream(scope, receive, send):
            observed.append((get_language(), t("action.confirm")))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        async def run():
            middleware = HttpLocaleMiddleware(downstream)
            await middleware(
                {
                    "type": "http",
                    "query_string": b"",
                    "headers": [
                        (b"cookie", b"gda.locale=ar-AE"),
                        (b"accept-language", b"en-US,en;q=0.9"),
                    ],
                },
                receive,
                send,
            )

        asyncio.run(run())
        assert observed == [("ar", "تأكيد التنفيذ")]
        assert (b"content-language", b"ar-AE") in messages[0]["headers"]
        assert get_language() == "zh"


class TestFallback:
    def test_unknown_lang_falls_back_to_zh(self):
        set_language("fr")
        val = t("action.confirm")
        assert val == "确认执行"

    def test_missing_key_returns_key(self):
        val = t("nonexistent.key.xyz")
        assert val == "nonexistent.key.xyz"

    def test_missing_key_in_en_falls_back_to_zh(self):
        # If a key exists in zh but not in en, fallback to zh
        set_language("en")
        # All keys should exist in both, so test with a hypothetical missing one
        val = t("totally.missing.key")
        assert val == "totally.missing.key"


# ===================================================================
# Interpolation
# ===================================================================

class TestInterpolation:
    def test_simple_interpolation(self):
        val = t("preview.record_count", count=42)
        assert "42" in val

    def test_multi_param_interpolation(self):
        val = t("error.retryable", err_msg="fail", category="transient", remaining=1)
        assert "fail" in val
        assert "transient" in val
        assert "1" in val

    def test_english_interpolation(self):
        set_language("en")
        val = t("preview.record_count", count=100)
        assert "100" in val
        assert "records" in val.lower() or "Records" in val


# ===================================================================
# Key parity — every source key should exist in all supported languages
# ===================================================================

class TestKeyParity:
    def test_translations_loaded(self):
        assert "zh" in _translations
        assert "en" in _translations
        assert "ar" in _translations

    def test_zh_keys_have_en(self):
        zh_keys = set(_translations["zh"].keys())
        en_keys = set(_translations["en"].keys())
        missing_in_en = zh_keys - en_keys
        assert not missing_in_en, f"Keys in zh but not in en: {missing_in_en}"

    def test_en_keys_have_zh(self):
        zh_keys = set(_translations["zh"].keys())
        en_keys = set(_translations["en"].keys())
        missing_in_zh = en_keys - zh_keys
        assert not missing_in_zh, f"Keys in en but not in zh: {missing_in_zh}"

    def test_zh_keys_have_ar(self):
        missing_in_ar = set(_translations["zh"]) - set(_translations["ar"])
        assert not missing_in_ar, f"Keys in zh but not in ar: {missing_in_ar}"

    def test_ar_keys_have_zh(self):
        missing_in_zh = set(_translations["ar"]) - set(_translations["zh"])
        assert not missing_in_zh, f"Keys in ar but not in zh: {missing_in_zh}"

    def test_no_empty_values(self):
        for lang in ("zh", "en", "ar"):
            for key, val in _translations[lang].items():
                assert val, f"Empty value for {lang}.{key}"

    def test_locale_files_have_no_duplicate_keys(self):
        class UniqueKeyLoader(yaml.SafeLoader):
            pass

        def construct_mapping(loader, node, deep=False):
            mapping = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                assert key not in mapping, f"Duplicate translation key: {key}"
                mapping[key] = loader.construct_object(value_node, deep=deep)
            return mapping

        UniqueKeyLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            construct_mapping,
        )
        locales_dir = Path(__file__).parent / "locales"
        for locale_file in locales_dir.glob("*.yaml"):
            yaml.load(locale_file.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)

    def test_memory_and_team_keys_are_symmetric(self):
        """Recently localized service responses must be present in every locale."""
        service_keys = {
            key
            for key in _translations["zh"]
            if key.startswith(("memory.", "team."))
        }
        assert len(service_keys) == 44
        for lang in ("zh", "en", "ar"):
            assert service_keys <= set(_translations[lang]), (
                f"Missing memory/team keys in {lang}: "
                f"{sorted(service_keys - set(_translations[lang]))}"
            )

    def test_interpolation_parameters_match_across_all_locales(self):
        """Every translation must preserve placeholders used by application code."""
        keys = set(_translations["zh"])

        def parameters(value):
            return {
                field_name
                for _, field_name, _, _ in Formatter().parse(value)
                if field_name
            }

        for key in keys:
            expected = parameters(_translations["zh"][key])
            for lang in ("en", "ar"):
                assert parameters(_translations[lang][key]) == expected, (
                    f"Interpolation mismatch for {lang}.{key}: "
                    f"expected {expected}, got {parameters(_translations[lang][key])}"
                )

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_memory_and_team_non_chinese_text(self, lang):
        """English and Arabic service messages must not fall back to Chinese text."""
        service_text = "\n".join(
            value
            for key, value in _translations[lang].items()
            if key.startswith(("memory.", "team."))
        )
        assert not re.search(r"[\u4e00-\u9fff]", service_text)

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_map_api_errors_are_localized(self, lang):
        """Basemap endpoints must not return a Chinese fallback error."""
        map_text = "\n".join(
            _translations[lang][key]
            for key in ("map_api.unauthorized", "map_api.basemap_not_found", "map_api.basemap_unavailable")
        )
        assert not re.search(r"[\u4e00-\u9fff]", map_text)

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_runtime_tool_and_agent_labels_have_no_chinese(self, lang):
        runtime_text = "\n".join(
            value
            for key, value in _translations[lang].items()
            if key.startswith(("app.tool_label.", "app.agent_label."))
        )
        assert runtime_text
        assert not re.search(r"[\u4e00-\u9fff]", runtime_text)

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_recent_backend_service_text_has_no_chinese(self, lang):
        """High-traffic backend response namespaces remain localized together."""
        prefixes = (
            "template.", "annotation.", "stream.", "quality.",
            "audit.", "version.", "database.", "connector.database.",
            "distribution.", "geocoding.", "knowledge_base.",
            "virtual_source.", "cleaning.", "nl2sql.", "kg.",
            "exploration.", "fusion.", "governance.", "masking.",
            "skill_dependency.", "messaging.", "virtual_api.",
            "asset.", "lite.", "skill_generator.", "tool_evolution.",
            "spatial_tier2.", "gis_processors.", "workflow.",
            "arcpy.", "watershed.",
            "ontology_query.",
            "ontology_draft.",
            "visualization.",
            "mcp_bridge.",
            "uwm_chat.",
            "uwm_service.",
            "twm_service.",
        )
        service_text = "\n".join(
            value
            for key, value in _translations[lang].items()
            if key.startswith(prefixes)
        )
        assert not re.search(r"[\u4e00-\u9fff]", service_text)


class TestHttpPageTranslations:
    def test_register_and_audit_page_keys_exist_in_every_language(self):
        page_keys = {
            key for key in _translations["zh"]
            if key.startswith(("register.", "audit_page."))
        }
        assert len(page_keys) >= 70
        for lang in ("zh", "en", "ar"):
            assert page_keys <= set(_translations[lang])

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_non_chinese_pages_do_not_leak_chinese_ui_text(self, lang):
        page_text = "\n".join(
            value for key, value in _translations[lang].items()
            if key.startswith(("register.", "audit_page."))
        )
        assert not re.search(r"[\u4e00-\u9fff]", page_text)


class TestTwmReportTranslations:
    @staticmethod
    def _service_without_repository():
        from data_agent.territory_world_model.service import TerritoryWorldModelService

        service = TerritoryWorldModelService.__new__(TerritoryWorldModelService)
        service.data_foundation_assessment = lambda: {
            "status": "review",
            "datasets": [{"id": "demo"}],
            "validation_snapshot": {
                "production_ready_observed_history_rows": 0,
                "production_policy_history_row_count": 0,
                "structural_fixture": {"row_count": 4, "structural_status": "pass"},
                "synthetic_experiment": {"row_count": 8},
                "project_review_context": {"rule_eval_count": 3, "review_task_count": 2},
            },
            "landing_readiness": {
                "engineering_mvp_supported": True,
                "key_blockers": [],
            },
        }
        return service

    @staticmethod
    def _data_foundation_service_without_repository():
        from data_agent.territory_world_model.service import TWM_DATA_FOUNDATION_DATASETS, TerritoryWorldModelService

        service = TerritoryWorldModelService.__new__(TerritoryWorldModelService)
        service._load_data_foundation_validation = lambda: {
            "summary": {
                "twm_production_ready_observed_history_rows": 0,
                "production_policy_history_row_count": 0,
                "twm_synthetic_experiment_row_count": 0,
                "twm_structural_fixture_row_count": 0,
                "twm_structural_fixture_structural_status": "unknown",
                "twm_synthetic_experiment_structural_status": "unknown",
                "production_policy_history_status": "not_provided",
            }
        }
        service._data_foundation_dataset_summary = lambda spec: {
            "id": spec["id"],
            "label": spec["label"],
            "positioning": spec["positioning"],
            "files": [],
            "file_count": 0,
            "not_for_production": True,
            "spatial_layer_catalog": [],
            "map_overlay_readiness": {"status": "unknown"},
        }
        assert len(TWM_DATA_FOUNDATION_DATASETS) == 3
        return service

    @pytest.mark.parametrize(
        ("lang", "roadmap_label", "readiness_label"),
        [
            ("zh", "自然资源演示收尾", "生产门"),
            ("en", "Natural resources demo closure", "Production gate"),
            ("ar", "إغلاق عرض الموارد الطبيعية", "بوابة الإنتاج"),
        ],
    )
    def test_roadmap_and_readiness_reports_localize_display_text(
        self,
        lang,
        roadmap_label,
        readiness_label,
    ):
        service = self._service_without_repository()
        set_language(lang)

        roadmap = service.roadmap_status_report()
        readiness = service.pilot_readiness_matrix_report()

        assert roadmap["phases"][0]["label"] == roadmap_label
        assert roadmap["phases"][0]["id"] == "demo_closure"
        assert roadmap["phases"][0]["status"] == "complete"
        assert roadmap["overall_status"] == "prototype_complete_review_only"
        assert readiness["dimensions"][-1]["label"] == readiness_label
        assert readiness["dimensions"][-1]["id"] == "production_gate"
        assert readiness["dimensions"][-1]["status"] == "blocked"
        assert readiness["overall_status"] == "blocked"

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_non_chinese_twm_reports_do_not_leak_fixed_chinese_text(self, lang):
        service = self._service_without_repository()
        set_language(lang)
        roadmap = service.roadmap_status_report()
        readiness = service.pilot_readiness_matrix_report()

        display_values = [roadmap["claim_boundary"]]
        for phase in roadmap["phases"]:
            display_values.extend([phase["label"], *phase["evidence"], *phase["remaining"]])
        for blocker in roadmap["blockers"]:
            display_values.extend(
                value
                for value in (blocker["current_value"], blocker["required_value"])
                if isinstance(value, str)
            )
        display_values.extend(item["action"] for item in roadmap["next_actions"])
        for dimension in readiness["dimensions"]:
            display_values.extend(
                [
                    dimension["label"],
                    *dimension["evidence"],
                    *dimension["missing"],
                    *dimension["test_data_work"],
                ]
            )
        for item in readiness["test_data_plan"]["items"]:
            display_values.extend([item["action"], item["why"]])

        assert not re.search(r"[\u4e00-\u9fff]", "\n".join(display_values))
        assert not any("{count}" in value or "{status}" in value for value in display_values)

    @pytest.mark.parametrize(
        ("lang", "positioning_name", "claim_boundary_fragment"),
        [
            ("zh", "分层 GIS 对象-关系-规则-证据状态", "每个 TWM 研究主张"),
            ("en", "Hierarchical GIS object-relation-rule-evidence state", "Every TWM research claim"),
            ("ar", "حالة GIS هرمية للكائن والعلاقة والقاعدة والدليل", "يجب أن يذكر كل ادعاء بحثي"),
        ],
    )
    def test_research_reports_localize_nested_claims_and_baselines(
        self,
        lang,
        positioning_name,
        claim_boundary_fragment,
    ):
        service = self._service_without_repository()
        set_language(lang)

        positioning = service.research_positioning()
        matrix = service.research_claim_matrix()

        assert positioning["core_technology"][0]["name"] == positioning_name
        assert claim_boundary_fragment in matrix["claim_boundary"]
        assert matrix["claims"][0]["claim_id"] == "C1_state_conflict_recall"
        assert matrix["claims"][0]["minimum_data"]
        assert matrix["claims"][0]["metrics"][0]["name"] == "hard_constraint_conflict_recall"
        assert matrix["baselines"][0]["baseline_id"] == "manual_gis_overlay_checklist"
        assert matrix["next_experiments"][0]["priority"] == "P0"

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_non_chinese_research_reports_do_not_leak_chinese(self, lang):
        service = self._service_without_repository()
        set_language(lang)
        positioning = service.research_positioning()
        matrix = service.research_claim_matrix()

        display_values = [positioning["research_question"], positioning["claim_boundary"]]
        for item in positioning["core_technology"]:
            display_values.extend(item.values())
        for item in positioning["innovation_hypotheses"]:
            display_values.extend(item.values())
        for field in (
            "unmet_need_hypotheses",
            "baselines_to_beat",
            "falsification_conditions",
            "minimum_evaluation_plan",
        ):
            display_values.extend(positioning[field])
        display_values.append(matrix["claim_boundary"])
        display_values.append(matrix["mentor_answer"])
        for claim in matrix["claims"]:
            for field in ("claim", "business_need", "core_technology", "current_evidence", "falsification"):
                display_values.append(claim[field])
            display_values.extend(claim["minimum_data"])
        for baseline in matrix["baselines"]:
            display_values.extend([baseline["label"], baseline["tests"], baseline["why_needed"]])
            display_values.extend(baseline["minimum_output"])
        for experiment in matrix["next_experiments"]:
            display_values.extend([experiment["experiment"], experiment["question"], experiment["decision"]])
            display_values.extend(experiment["required_data"])

        assert not re.search(r"[\u4e00-\u9fff]", "\n".join(str(value) for value in display_values))

    @pytest.mark.parametrize(
        ("lang", "export_label", "template_label"),
        [
            ("zh", "人工 GIS 叠加加清单导出", "C1 同案硬约束冲突召回导出"),
            ("en", "Manual GIS overlay plus checklist export", "C1 same-case hard-constraint conflict recall export"),
            ("ar", "تصدير تراكب GIS يدوي مع قائمة تحقق", "تصدير استدعاء تعارض القيود الصارمة C1 للحالات نفسها"),
        ],
    )
    def test_baseline_export_schema_and_templates_localize_display_text(
        self,
        lang,
        export_label,
        template_label,
    ):
        service = self._service_without_repository()
        set_language(lang)
        schema = service.baseline_export_schema()
        templates = service.baseline_export_templates()

        assert schema["export_types"][0]["label"] == export_label
        assert templates["templates"][0]["label"] == template_label
        assert templates["templates"][0]["field_descriptions"][0]["name"] == "case_id"
        assert templates["templates"][0]["minimum_real_data_gate"]["same_case_join_key"] == "case_id"
        assert {item["claim_id"] for item in templates["templates"]} >= {
            "C1_state_conflict_recall",
            "C2_audit_defensibility",
            "C3_action_conditioned_triage",
        }

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_non_chinese_baseline_export_payload_does_not_leak_chinese(self, lang):
        service = self._service_without_repository()
        set_language(lang)
        schema = service.baseline_export_schema()
        templates = service.baseline_export_templates()

        def strings(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                return [item for child in value.values() for item in strings(child)]
            if isinstance(value, list):
                return [item for child in value for item in strings(child)]
            return []

        display_text = "\n".join(strings(schema) + strings(templates))
        assert not re.search(r"[\u4e00-\u9fff]", display_text)

    @pytest.mark.parametrize("lang", ["zh", "en", "ar"])
    def test_baseline_validation_comparison_pipeline_localize_report_actions(self, lang):
        service = self._service_without_repository()
        set_language(lang)

        validation = service.baseline_export_validation_report(
            {"claim_id": "C1_state_conflict_recall", "baseline_id": "manual_gis_overlay_checklist"}
        )
        comparison = service.baseline_comparison_report(
            {"claim_id": "C1_state_conflict_recall", "baseline_id": "manual_gis_overlay_checklist"}
        )
        pipeline = service.baseline_evidence_pipeline_report(
            {
                "claim_id": "C1_state_conflict_recall",
                "baseline_id": "manual_gis_overlay_checklist",
                "validate_only": True,
            }
        )

        assert validation["schema"].endswith("baseline_export_validation_report.v1")
        assert comparison["schema"].endswith("baseline_comparison_report.v1")
        assert pipeline["schema"].endswith("baseline_evidence_pipeline_report.v1")
        assert validation["next_actions"]
        assert comparison["next_actions"]
        assert pipeline["next_actions"]
        assert validation["claim"]["claim_id"] == "C1_state_conflict_recall"
        assert comparison["baseline"]["baseline_id"] == "manual_gis_overlay_checklist"

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_non_chinese_baseline_run_reports_do_not_leak_chinese(self, lang):
        service = self._service_without_repository()
        set_language(lang)
        reports = [
            service.baseline_export_validation_report({}),
            service.baseline_comparison_report({}),
            service.baseline_evidence_pipeline_report({"validate_only": True}),
        ]

        def strings(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                return [item for child in value.values() for item in strings(child)]
            if isinstance(value, list):
                return [item for child in value for item in strings(child)]
            return []

        display_text = "\n".join(item for report in reports for item in strings(report))
        assert not re.search(r"[\u4e00-\u9fff]", display_text)

    @pytest.mark.parametrize(
        ("lang", "dataset_label", "blocker_fragment"),
        [
            ("zh", "璧山演示工程夹具", "生产可用观察历史行数为 0"),
            ("en", "Bishan demo engineering fixture", "Production-ready observed-history rows=0"),
            ("ar", "تركيبة هندسية لعرض بيشان", "صفوف السجل المرصود الجاهز للإنتاج=0"),
        ],
    )
    def test_data_foundation_assessment_localizes_boundary_text(self, lang, dataset_label, blocker_fragment):
        service = self._data_foundation_service_without_repository()
        set_language(lang)
        assessment = service.data_foundation_assessment()

        assert assessment["datasets"][0]["label"] == dataset_label
        assert blocker_fragment in assessment["landing_readiness"]["key_blockers"][0]
        assert assessment["supported_problems"][0]["problem"]
        assert assessment["unsupported_claims"][0]["claim"]
        assert assessment["required_next_data"][0]["priority"] == "P0"

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_non_chinese_data_foundation_assessment_does_not_leak_chinese(self, lang):
        service = self._data_foundation_service_without_repository()
        set_language(lang)
        assessment = service.data_foundation_assessment()

        def strings(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                return [item for child in value.values() for item in strings(child)]
            if isinstance(value, list):
                return [item for child in value for item in strings(child)]
            return []

        assert not re.search(r"[\u4e00-\u9fff]", "\n".join(strings(assessment)))

    @staticmethod
    def _data_foundation_downstream_service():
        from data_agent.territory_world_model.service import TWM_DATA_FOUNDATION_DATASETS, TerritoryWorldModelService

        service = TerritoryWorldModelService.__new__(TerritoryWorldModelService)
        spec = TWM_DATA_FOUNDATION_DATASETS[0]
        service.data_foundation_assessment = lambda: {
            "datasets": [{
                "id": spec["id"],
                "files": [{
                    "path": "synthetic_projects.geojson",
                    "unit": "feature",
                    "exists": True,
                    "count": 2,
                    "synthetic_count": 2,
                    "not_for_production_count": 2,
                }],
                "file_count": 1,
                "total_count": 2,
                "synthetic_count": 2,
                "not_for_production_count": 2,
                "not_for_production": True,
                "spatial_layer_catalog": [{
                    "path": "synthetic_projects.geojson",
                    "label": "projects",
                    "feature_count": 2,
                    "bbox": [106.0, 29.0, 106.2, 29.2],
                    "crs_diagnostic": {
                        "status": "wgs84_lonlat",
                        "map_overlay_ready": True,
                        "warning_code": None,
                        "message": "localized diagnostic",
                    },
                }],
                "map_overlay_readiness": {
                    "status": "ready",
                    "message": "localized overlay readiness",
                },
            }],
            "validation_snapshot": {
                "production_ready_observed_history_rows": 0,
                "production_policy_history_row_count": 0,
            },
            "required_next_data": [{
                "priority": "P0",
                "data": "localized next data",
                "minimum": "localized minimum",
                "unlocks": "localized unlocks",
            }],
        }
        return service

    @pytest.mark.parametrize(
        ("lang", "dataset_label", "readiness_fragment"),
        [
            ("zh", "璧山演示工程夹具", "可用于字段、空间范围和链路回归核查"),
            ("en", "Bishan demo engineering fixture", "Useful for field, spatial-extent and lineage regression checks"),
            ("ar", "تركيبة هندسية لعرض بيشان", "مفيدة لفحوص انحدار الحقول والامتداد المكاني والنسب"),
        ],
    )
    def test_data_foundation_lineage_and_crs_plan_localize_nested_text(
        self, lang, dataset_label, readiness_fragment
    ):
        service = self._data_foundation_downstream_service()
        set_language(lang)

        lineage = service.data_foundation_lineage_report("twm_bishan_demo")
        crs_plan = service.data_foundation_crs_remediation_plan("twm_bishan_demo")

        assert lineage["dataset_label"] == dataset_label
        assert readiness_fragment in lineage["files"][0]["readiness_note"]
        assert lineage["readiness_gates"][0]["current_value"]
        assert lineage["required_next_data"][0]["data"] == "localized next data"
        assert crs_plan["layers"][0]["conversion_steps"][0]["acceptance"]
        assert crs_plan["claim_boundary"]

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_data_foundation_downstream_reports_do_not_leak_chinese(self, lang):
        service = self._data_foundation_downstream_service()
        set_language(lang)
        reports = [
            service.data_foundation_lineage_report("twm_bishan_demo"),
            service.data_foundation_crs_remediation_plan("twm_bishan_demo"),
            service.data_foundation_authoritative_templates(),
            service._data_foundation_crs_diagnostic(None),
            service._data_foundation_crs_diagnostic([1000, 1000, 2000, 2000]),
            service._data_foundation_map_overlay_readiness([]),
            {"claim_boundary": t("twm_service.data_foundation.layer_detail.claim_boundary")},
        ]

        def strings(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                return [item for child in value.values() for item in strings(child)]
            if isinstance(value, list):
                return [item for child in value for item in strings(child)]
            return []

        assert not re.search(r"[\u4e00-\u9fff]", "\n".join(strings(reports)))

    @pytest.mark.parametrize(
        ("lang", "template_label"),
        [
            ("zh", "当前地块权威图层"),
            ("en", "Current land-parcel authoritative layer"),
            ("ar", "طبقة قطع الأراضي الموثوقة الحالية"),
        ],
    )
    def test_authoritative_templates_localize_labels_and_preserve_contract(self, lang, template_label):
        from data_agent.territory_world_model.service import TerritoryWorldModelService

        service = TerritoryWorldModelService.__new__(TerritoryWorldModelService)
        set_language(lang)
        report = service.data_foundation_authoritative_templates()

        assert report["templates"][0]["label"] == template_label
        assert report["templates"][0]["template_id"] == "parcel_current_authoritative"
        assert report["templates"][0]["required_fields"][0] == "geometry"
        assert report["readiness_gates"][0]["id"] == "custodian_signoff"
        assert report["onboarding_steps"]

    @pytest.mark.parametrize("lang", ["en", "ar"])
    def test_data_foundation_map_preview_and_layer_detail_localize_contract(
        self, lang, tmp_path, monkeypatch
    ):
        from data_agent.territory_world_model.service import TerritoryWorldModelService
        import data_agent.territory_world_model.service as service_module

        service = TerritoryWorldModelService.__new__(TerritoryWorldModelService)
        dataset_root = tmp_path / "data"
        dataset_root.mkdir()
        (dataset_root / "parcel_current.geojson").write_text(
            '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[106.0,29.0]},"properties":{"parcel_id":"p-1"}}]}',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            service_module,
            "TWM_DATA_FOUNDATION_DATASETS",
            ({
                "id": "twm_bishan_demo",
                "label": "Bishan demo engineering fixture",
                "path": "data",
                "positioning": "fixture",
                "nature": "fixture",
                "files": {"parcel_current.geojson": "feature"},
            },),
        )
        service._repo_root = lambda: tmp_path
        set_language(lang)
        preview = service.data_foundation_map_preview("twm_bishan_demo", max_features_per_layer=1)
        detail = service.data_foundation_layer_detail("twm_bishan_demo", "parcel_current.geojson", sample_limit=1)

        assert preview["schema"].endswith("data_foundation_map_preview.v1")
        assert preview["label"]
        assert preview["layers"][0]["crs_diagnostic"]["message"]
        assert detail["layer_path"] == "parcel_current.geojson"
        assert detail["sample_record_count"] == 1
        assert detail["claim_boundary"]

    @pytest.mark.parametrize(
        ("lang", "rule_label", "support_label", "review_label"),
        [
            ("zh", "规则判断", "支撑材料", "人工复核"),
            ("en", "Rule assessment", "Support material", "Human review"),
            ("ar", "تقييم القاعدة", "مادة داعمة", "مراجعة بشرية"),
        ],
    )
    def test_state_graph_fallback_labels_localize(self, lang, rule_label, support_label, review_label):
        from types import SimpleNamespace
        from data_agent.territory_world_model.service import TerritoryWorldModelService

        service = TerritoryWorldModelService.__new__(TerritoryWorldModelService)
        set_language(lang)
        rule_node = service._state_graph_rule_hit_node(
            SimpleNamespace(id="rule-1", rule_id="", severity="low", risk_score=0, hit_status="", explanation="")
        )
        support_node = service._state_graph_support_material_node(
            SimpleNamespace(id="evidence-1", source_ref="", evidence_type="", payload={}, source_system="", checksum="")
        )
        review_node = service._state_graph_review_task_node(
            SimpleNamespace(id="review-1", decision="", status="", comment="")
        )

        assert rule_node["label"] == rule_label
        assert support_node["label"] == support_label
        assert review_node["label"] == review_label


# ===================================================================
# Preview functions with i18n
# ===================================================================

class TestPreviewI18n:
    def test_dtype_label_zh(self):
        import numpy as np
        from data_agent.utils import _dtype_label
        assert _dtype_label(np.dtype("float64")) == "数值"

    def test_dtype_label_en(self):
        import numpy as np
        from data_agent.utils import _dtype_label
        set_language("en")
        assert _dtype_label(np.dtype("float64")) == "Numeric"

    def test_quality_good_zh(self):
        import geopandas as gpd
        from shapely.geometry import Point
        from data_agent.utils import _preview_quality_indicators
        gdf = gpd.GeoDataFrame(
            {"a": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326"
        )
        text = "\n".join(_preview_quality_indicators(gdf))
        assert "良好" in text

    def test_quality_good_en(self):
        import geopandas as gpd
        from shapely.geometry import Point
        from data_agent.utils import _preview_quality_indicators
        set_language("en")
        gdf = gpd.GeoDataFrame(
            {"a": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326"
        )
        text = "\n".join(_preview_quality_indicators(gdf))
        assert "good" in text.lower()

    def test_generate_preview_en(self, tmp_path):
        import pandas as pd
        from data_agent.utils import _generate_upload_preview
        set_language("en")
        path = tmp_path / "test.csv"
        pd.DataFrame({
            "lat": [30.0, 31.0], "lon": [110.0, 111.0], "value": [1, 2]
        }).to_csv(path, index=False)
        result = _generate_upload_preview(str(path))
        assert "Data Preview" in result
        assert "records" in result.lower() or "Records" in result
