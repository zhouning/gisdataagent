"""Tests for the production @NL2SQL agent builder."""


def test_mention_nl2sql_uses_single_tool_for_gemma_ollama(monkeypatch):
    from google.adk.models.lite_llm import LiteLlm
    from data_agent import agent as agent_module
    from data_agent.nl2semantic2sql_direct_agent import DirectNL2SemanticSQLAgent

    monkeypatch.delenv("NL2SQL_AGENT_MODEL", raising=False)
    model = LiteLlm(
        model="ollama_chat/Gemma4:26b",
        extra_body={"think": False},
        timeout=600,
    )
    monkeypatch.setattr(agent_module, "get_model_for_tier", lambda *_args, **_kwargs: model)

    built = agent_module._build_mention_nl2sql_agent()

    assert isinstance(built, DirectNL2SemanticSQLAgent)


def test_mention_nl2sql_prefers_nl2sql_agent_model_env(monkeypatch):
    from data_agent import agent as agent_module
    from data_agent.model_gateway import create_model
    from data_agent.nl2semantic2sql_direct_agent import DirectNL2SemanticSQLAgent

    monkeypatch.setenv("NL2SQL_AGENT_MODEL", "gemma4-26b-host9")
    monkeypatch.setattr(
        agent_module,
        "get_model_for_tier",
        lambda *_args, **_kwargs: create_model("gemini-2.5-flash"),
    )

    built = agent_module._build_mention_nl2sql_agent()

    assert isinstance(built, DirectNL2SemanticSQLAgent)


def test_mention_nl2sql_keeps_full_tool_surface_for_non_gemma(monkeypatch):
    from data_agent import agent as agent_module
    from data_agent.model_gateway import create_model

    monkeypatch.delenv("NL2SQL_AGENT_MODEL", raising=False)
    model = create_model("gemini-2.5-flash")
    monkeypatch.setattr(agent_module, "get_model_for_tier", lambda *_args, **_kwargs: model)

    built = agent_module._build_mention_nl2sql_agent()

    assert len(built.tools) == 4
