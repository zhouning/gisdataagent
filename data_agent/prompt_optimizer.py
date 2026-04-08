"""
Prompt Auto-Optimizer — bad case collection, failure analysis, prompt improvement.

Collects bad cases from eval history, pipeline failures, and user feedback.
Analyzes failure patterns using LLM. Generates prompt improvement suggestions
and applies them as new prompt versions via the PromptRegistry.
"""
import json
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .observability import get_logger

logger = get_logger("prompt_optimizer")


def _get_genai_client():
    """Get a genai Client instance. Separated for easy mocking in tests."""
    from google import genai
    return genai.Client()


class BadCaseCollector:
    """Collect bad cases from multiple sources."""

    async def collect_from_eval_history(
        self, min_score: float = 0.5, limit: int = 50
    ) -> list[dict]:
        """Get low-scoring evaluation runs.

        Returns eval runs where overall_score < min_score, ordered by
        lowest score first.
        """
        engine = get_engine()
        if not engine:
            return []
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, run_id, pipeline, model, overall_score,
                               pass_rate, verdict, details, created_at
                        FROM agent_eval_history
                        WHERE overall_score < :min_score
                        ORDER BY overall_score ASC
                        LIMIT :lim
                    """),
                    {"min_score": min_score, "lim": limit},
                ).fetchall()
            return [
                {
                    "source": "eval_history",
                    "id": r[0],
                    "run_id": r[1],
                    "pipeline": r[2],
                    "model": r[3],
                    "score": float(r[4] or 0),
                    "pass_rate": float(r[5] or 0),
                    "verdict": r[6],
                    "details": r[7] if isinstance(r[7], dict) else json.loads(r[7] or "{}"),
                    "created_at": r[8].isoformat() if r[8] else None,
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Failed to collect eval bad cases: %s", e)
            return []

    async def collect_from_pipeline_failures(
        self, days: int = 7, limit: int = 50
    ) -> list[dict]:
        """Get recent pipeline failures with error details.

        Queries the audit_log for pipeline_complete events with failure status.
        """
        engine = get_engine()
        if not engine:
            return []
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, username, details, created_at
                        FROM agent_audit_log
                        WHERE action = 'pipeline_complete'
                          AND status = 'failure'
                          AND created_at >= NOW() - make_interval(days => :d)
                        ORDER BY created_at DESC
                        LIMIT :lim
                    """),
                    {"d": days, "lim": limit},
                ).fetchall()
            return [
                {
                    "source": "pipeline_failure",
                    "id": r[0],
                    "username": r[1],
                    "details": r[2] if isinstance(r[2], dict) else json.loads(r[2] or "{}"),
                    "created_at": r[3].isoformat() if r[3] else None,
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Failed to collect pipeline failures: %s", e)
            return []

    async def collect_from_user_feedback(
        self, min_rating: int = 2, limit: int = 50
    ) -> list[dict]:
        """Get low-rated user feedback.

        Queries the audit_log for user_feedback events with low ratings.
        Feedback details are expected to contain a 'rating' field (1-5).
        """
        engine = get_engine()
        if not engine:
            return []
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, username, details, created_at
                        FROM agent_audit_log
                        WHERE action = 'user_feedback'
                          AND (details->>'rating')::int <= :min_rating
                        ORDER BY created_at DESC
                        LIMIT :lim
                    """),
                    {"min_rating": min_rating, "lim": limit},
                ).fetchall()
            return [
                {
                    "source": "user_feedback",
                    "id": r[0],
                    "username": r[1],
                    "details": r[2] if isinstance(r[2], dict) else json.loads(r[2] or "{}"),
                    "created_at": r[3].isoformat() if r[3] else None,
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Failed to collect user feedback: %s", e)
            return []

    async def collect_from_agent_feedback(
        self, limit: int = 50
    ) -> list[dict]:
        """Get downvotes from agent_feedback table (v19.0).

        Reads from the dedicated feedback table added in v19.0,
        complementing the legacy audit_log source.
        """
        engine = get_engine()
        if not engine:
            return []
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, username, query_text, response_text,
                               pipeline_type, issue_description, created_at
                        FROM agent_feedback
                        WHERE vote = -1
                          AND resolved_at IS NULL
                        ORDER BY created_at DESC
                        LIMIT :lim
                    """),
                    {"lim": limit},
                ).fetchall()
            return [
                {
                    "source": "agent_feedback",
                    "id": r[0],
                    "username": r[1],
                    "pipeline": r[4] or "unknown",
                    "details": {
                        "query": r[2] or "",
                        "response": (r[3] or "")[:500],
                        "issue": r[5] or "",
                    },
                    "created_at": r[6].isoformat() if r[6] else None,
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("Failed to collect from agent_feedback: %s", e)
            return []

    async def collect_all(
        self,
        min_score: float = 0.5,
        days: int = 7,
        min_rating: int = 2,
        limit: int = 50,
    ) -> list[dict]:
        """Collect bad cases from all sources (including v19.0 agent_feedback)."""
        eval_cases = await self.collect_from_eval_history(min_score, limit)
        pipeline_cases = await self.collect_from_pipeline_failures(days, limit)
        feedback_cases = await self.collect_from_user_feedback(min_rating, limit)
        agent_fb_cases = await self.collect_from_agent_feedback(limit)
        return eval_cases + pipeline_cases + feedback_cases + agent_fb_cases


class FailureAnalyzer:
    """Analyze bad cases to identify failure patterns."""

    async def analyze(self, bad_cases: list[dict]) -> dict:
        """Use LLM to analyze failure patterns.

        Returns:
            {
                "patterns": [
                    {
                        "category": "...",
                        "description": "...",
                        "frequency": N,
                        "examples": [...]
                    }
                ],
                "root_causes": ["..."],
                "affected_prompts": ["domain/prompt_key", ...]
            }
        """
        if not bad_cases:
            return {"patterns": [], "root_causes": [], "affected_prompts": []}

        # Build a summary of bad cases for the LLM
        cases_summary = []
        for case in bad_cases[:30]:  # Limit to avoid token overflow
            summary = {
                "source": case.get("source", "unknown"),
                "pipeline": case.get("pipeline", ""),
                "score": case.get("score"),
                "verdict": case.get("verdict"),
                "details": case.get("details", {}),
            }
            cases_summary.append(summary)

        prompt = f"""Analyze the following bad cases from an AI agent system and identify failure patterns.

Bad cases (JSON):
{json.dumps(cases_summary, ensure_ascii=False, default=str)[:4000]}

Respond in valid JSON with this exact structure:
{{
    "patterns": [
        {{
            "category": "category name (e.g., data_format, timeout, prompt_unclear, tool_error)",
            "description": "brief description of the pattern",
            "frequency": <number of cases matching this pattern>,
            "examples": ["brief example 1", "brief example 2"]
        }}
    ],
    "root_causes": ["root cause 1", "root cause 2"],
    "affected_prompts": ["domain/prompt_key", ...]
}}

Rules:
- Group similar failures into patterns
- Identify 2-5 distinct patterns
- Root causes should be actionable
- affected_prompts should list domain/prompt_key pairs that likely need improvement
- Keep descriptions concise"""

        try:
            client = _get_genai_client()
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            # Parse JSON from response
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1]  # remove first line
                if text.endswith("```"):
                    text = text[: -len("```")]
                text = text.strip()
            result = json.loads(text)
            # Validate structure
            if "patterns" not in result:
                result["patterns"] = []
            if "root_causes" not in result:
                result["root_causes"] = []
            if "affected_prompts" not in result:
                result["affected_prompts"] = []
            return result
        except Exception as e:
            logger.warning("Failure analysis LLM call failed: %s", e)
            # Fallback: basic statistical analysis without LLM
            source_counts: dict[str, int] = {}
            for case in bad_cases:
                src = case.get("source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1
            patterns = [
                {
                    "category": src,
                    "description": f"{count} bad cases from {src}",
                    "frequency": count,
                    "examples": [],
                }
                for src, count in source_counts.items()
            ]
            return {
                "patterns": patterns,
                "root_causes": [f"LLM analysis unavailable: {e}"],
                "affected_prompts": [],
            }


class PromptOptimizer:
    """Generate prompt improvement suggestions."""

    async def suggest_improvements(
        self,
        domain: str,
        prompt_key: str,
        failure_analysis: dict,
    ) -> dict:
        """Generate improved prompt text based on failure analysis.

        Returns:
            {
                "original_prompt": "...",
                "suggested_prompt": "...",
                "changes": ["added X", "clarified Y", ...],
                "expected_improvement": "..."
            }
        """
        # Get current prompt
        from .prompt_registry import PromptRegistry
        registry = PromptRegistry()
        try:
            original_prompt = registry.get_prompt(domain, prompt_key)
        except Exception:
            original_prompt = ""

        if not original_prompt:
            return {
                "original_prompt": "",
                "suggested_prompt": "",
                "changes": [],
                "expected_improvement": "Cannot optimize: original prompt not found",
            }

        patterns = failure_analysis.get("patterns", [])
        root_causes = failure_analysis.get("root_causes", [])

        prompt = f"""You are a prompt engineering expert. Improve the following agent prompt
based on the identified failure patterns.

CURRENT PROMPT:
{original_prompt[:3000]}

FAILURE PATTERNS:
{json.dumps(patterns, ensure_ascii=False, default=str)[:2000]}

ROOT CAUSES:
{json.dumps(root_causes, ensure_ascii=False, default=str)[:500]}

Respond in valid JSON with this exact structure:
{{
    "suggested_prompt": "the improved prompt text (complete, ready to use)",
    "changes": ["change 1 description", "change 2 description"],
    "expected_improvement": "brief explanation of expected improvement"
}}

Rules:
- Preserve the original prompt's core intent and structure
- Add guardrails for the identified failure patterns
- Make instructions more explicit where failures suggest ambiguity
- Keep the prompt concise — do not bloat unnecessarily
- The suggested_prompt must be a complete replacement, not a diff"""

        try:
            client = _get_genai_client()
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[: -len("```")]
                text = text.strip()
            result = json.loads(text)
            result["original_prompt"] = original_prompt
            return result
        except Exception as e:
            logger.warning("Prompt optimization LLM call failed: %s", e)
            return {
                "original_prompt": original_prompt,
                "suggested_prompt": "",
                "changes": [],
                "expected_improvement": f"LLM call failed: {e}",
            }

    async def apply_suggestion(
        self,
        domain: str,
        prompt_key: str,
        suggested_prompt: str,
        environment: str = "dev",
    ) -> dict:
        """Save the suggestion as a new prompt version (in dev environment).

        Returns:
            {"version_id": int, "environment": str, "status": "created"}
        """
        from .prompt_registry import PromptRegistry
        registry = PromptRegistry()
        try:
            version_id = registry.create_version(
                domain=domain,
                prompt_key=prompt_key,
                prompt_text=suggested_prompt,
                env=environment,
                change_reason="Auto-optimized based on failure analysis",
                created_by="prompt_optimizer",
            )
            return {
                "version_id": version_id,
                "environment": environment,
                "status": "created",
            }
        except Exception as e:
            logger.warning("Failed to apply prompt suggestion: %s", e)
            return {
                "version_id": None,
                "environment": environment,
                "status": "error",
                "error": str(e),
            }
