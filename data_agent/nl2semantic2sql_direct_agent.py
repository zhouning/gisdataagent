"""Deterministic ADK agent for Gemma/Ollama NL2Semantic2SQL."""
from __future__ import annotations

import re
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types


class DirectNL2SemanticSQLAgent(BaseAgent):
    """Run NL2Semantic2SQL directly, without LLM tool-call orchestration."""

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        question = _extract_user_question(ctx.user_content)
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_function_call(
                        name="run_nl2semantic2sql",
                        args={"user_question": question},
                    )
                ],
            ),
        )

        from .nl2sql_executor import run_nl2semantic2sql

        result = run_nl2semantic2sql(question)
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_function_response(
                        name="run_nl2semantic2sql",
                        response={"result": result},
                    )
                ],
            ),
        )
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=result)],
            ),
        )


def _extract_user_question(content: types.Content | None) -> str:
    if not content or not content.parts:
        return ""
    text = "\n".join(part.text or "" for part in content.parts if part.text)
    text = text.strip()
    if not text:
        return ""

    # CQ full-mode prompts wrap the natural question in a larger schema block.
    m = re.search(
        r"(?:^|\n)Question:\s*(?P<q>.*?)(?:\n\s*\nGenerate ONE\b|\Z)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group("q").strip()
    return text
