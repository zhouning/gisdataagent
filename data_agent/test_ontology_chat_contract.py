import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from data_agent.intent_router import classify_intent
from data_agent.message_handler import select_pipeline_agent
from data_agent.ontology_presentation import (
    format_ontology_result_for_chat,
    parse_ontology_tool_response,
)
from data_agent.toolsets.ontology_tools import OntologyToolset, query_ontology

ROOT = Path(__file__).resolve().parents[1]


def test_ontology_intent_shortcut_does_not_need_router_model():
    intent, reason, tokens, categories, language, mode = classify_intent(
        "农用地、耕地和非耕农用地是什么关系？"
    )

    assert intent == "ONTOLOGY"
    assert reason == "natural_resource_ontology_query"
    assert tokens == 0
    assert categories == {"ontology_query"}
    assert language == "zh"
    assert mode == "agentic"


def test_land_transition_question_routes_to_ontology_without_router_model():
    intent, reason, tokens, categories, language, mode = classify_intent(
        "农用地通过什么过程可以转为建设用地？"
    )

    assert intent == "ONTOLOGY"
    assert reason == "natural_resource_ontology_query"
    assert tokens == 0
    assert categories == {"ontology_query"}
    assert language == "zh"
    assert mode == "agentic"


def test_heping_review_scenario_routes_to_ontology_without_router_model():
    intent, reason, tokens, categories, language, mode = classify_intent(
        "运行和平村用地转换辅助预审，并在地图上展示结果。"
    )

    assert intent == "ONTOLOGY"
    assert reason == "natural_resource_ontology_query"
    assert tokens == 0
    assert categories == {"ontology_query"}
    assert language == "zh"
    assert mode == "agentic"


def test_ontology_pipeline_uses_dedicated_agent():
    agent, pipeline_type, pipeline_name = select_pipeline_agent("ONTOLOGY")

    assert agent.name == "OntologyAnalysisAgent"
    assert pipeline_type == "ontology"
    assert pipeline_name == "Ontology Analysis Agent"


def test_ontology_toolset_initializes_adk_23_base_contract():
    toolset = OntologyToolset(tool_filter=["query_ontology"])

    assert toolset._use_invocation_cache is True
    assert toolset.tool_filter == ["query_ontology"]
    assert [tool.name for tool in asyncio.run(toolset.get_tools())] == ["query_ontology"]


def test_ontology_tools_skip_redundant_llm_summarization(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_RUNTIME_BACKEND", "package")
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    tool_context = SimpleNamespace(actions=SimpleNamespace(skip_summarization=False))

    query_ontology("hierarchy", subject="土地", tool_context=tool_context)

    assert tool_context.actions.skip_summarization is True


def test_hierarchy_tool_result_has_deterministic_chat_answer(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_RUNTIME_BACKEND", "package")
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    raw = {"result": query_ontology("hierarchy", subject="土地", depth=2, limit=60)}
    parsed = parse_ontology_tool_response(raw)

    assert parsed is not None
    rendered = format_ontology_result_for_chat(parsed)
    assert "土地的领域类层级" in rendered
    assert "农用地 (`AgriculturalLand`)" in rendered
    assert "建设用地 (`ConstructionLand`)" in rendered
    assert "未利用地 (`UnusedLand`)" in rendered
    assert "耕地 (`CultivatedLand`)" in rendered
    assert "本体 `V2.0.1`" in rendered


def test_transition_tool_result_is_rendered_from_structured_evidence(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_RUNTIME_BACKEND", "package")
    monkeypatch.delenv("ONTOLOGY_SPARQL_ENDPOINT", raising=False)
    parsed = json.loads(
        query_ontology(
            "transition_rules",
            subject="农用地",
            target="建设用地",
            depth=3,
        )
    )

    rendered = format_ontology_result_for_chat(parsed)
    assert "农用地 → 建设用地" in rendered
    assert "建设占用" in rendered
    assert "农业结构调整" not in rendered
    assert "审批文件" in rendered


def test_frontend_contract_dispatches_workspace_to_both_ontology_views():
    chat = (ROOT / "frontend/src/components/ChatPanel.tsx").read_text(encoding="utf-8")
    panel = (ROOT / "frontend/src/components/DataPanel.tsx").read_text(encoding="utf-8")
    ontology = (ROOT / "frontend/src/components/datapanel/OntologyTab.tsx").read_text(
        encoding="utf-8"
    )
    demo = (
        ROOT / "frontend/src/components/datapanel/NaturalResourceOntologyDemoTab.tsx"
    ).read_text(encoding="utf-8")

    assert "dispatchWorkspaceUpdate(data.workspace_update)" in chat
    assert "__pendingGdaWorkspaceUpdate = update" in chat
    assert "gda-workspace-update" in panel
    assert "detail.tab !== 'ontology'" in ontology
    assert "pending?.tab === 'ontology'" in ontology
    assert "detail.tab !== 'ontology_demo'" in demo
    assert "pending?.tab === 'ontology_demo'" in demo
    assert "detail.auto_run" in demo
    assert "run.attestation?.passed !== true" in demo
    assert "run.okf_reference?.resource" in demo
    assert "ontologyDemo.results.okfPassed" in demo
