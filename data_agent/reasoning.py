"""
Advanced Reasoning — chain-of-thought + confidence scoring + reasoning traces (v11.0.2).

Provides a ReasoningPlugin that injects chain-of-thought instructions,
extracts reasoning traces from LLM output, and optionally scores confidence.

All operations are non-fatal (never raise to caller).
"""
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    from .observability import get_logger
    logger = get_logger("reasoning")
except Exception:
    import logging
    logger = logging.getLogger("reasoning")


REASONING_ENABLED = os.environ.get("REASONING_ENABLED", "true").lower() == "true"
STATE_KEY = "__reasoning_trace__"

# Chain-of-thought injection prefix
COT_PREFIX = """## 推理过程
对于每个决策步骤，请先在 <reasoning>...</reasoning> 标签中写出你的推理过程：
1. 观察到的数据特征
2. 选择该方法/工具的理由
3. 对结果的预期
4. 潜在风险或替代方案
注意：<reasoning> 标签内容仅用于内部推理记录，不会直接展示给用户。"""

# Regex for extracting reasoning blocks
_REASONING_RE = re.compile(r'<reasoning>(.*?)</reasoning>', re.DOTALL)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ReasoningStep:
    """A single step in the reasoning trace."""
    thought: str = ""
    action: str = ""
    observation: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "thought": self.thought,
            "action": self.action,
            "observation": self.observation,
            "timestamp": self.timestamp,
        }


@dataclass
class ConfidenceScore:
    """Structured confidence assessment of a pipeline result."""
    overall: float = 0.0  # 0-1
    data_quality: float = 0.0
    method_appropriateness: float = 0.0
    result_completeness: float = 0.0
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "overall": round(self.overall, 3),
            "data_quality": round(self.data_quality, 3),
            "method_appropriateness": round(self.method_appropriateness, 3),
            "result_completeness": round(self.result_completeness, 3),
            "explanation": self.explanation,
        }


@dataclass
class ReasoningTrace:
    """Complete reasoning trace for a pipeline execution."""
    steps: list[ReasoningStep] = field(default_factory=list)
    confidence: Optional[ConfidenceScore] = None
    raw_reasoning_blocks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "confidence": self.confidence.to_dict() if self.confidence else None,
            "step_count": len(self.steps),
        }

    @classmethod
    def from_session_state(cls, state: dict) -> "ReasoningTrace":
        """Extract reasoning trace from ADK session state."""
        raw = state.get(STATE_KEY, [])
        if not raw:
            return cls()

        steps = []
        raw_blocks = []
        for item in raw:
            if isinstance(item, dict):
                steps.append(ReasoningStep(**{k: item.get(k, "") for k in ("thought", "action", "observation")}))
            elif isinstance(item, str):
                raw_blocks.append(item)
                steps.append(ReasoningStep(thought=item))

        return cls(steps=steps, raw_reasoning_blocks=raw_blocks)


# ---------------------------------------------------------------------------
# Reasoning extraction
# ---------------------------------------------------------------------------

def extract_reasoning_blocks(text: str) -> tuple[list[str], str]:
    """Extract <reasoning> blocks from text.

    Returns (list_of_reasoning_blocks, cleaned_text_without_blocks).
    """
    if not text:
        return [], ""

    blocks = _REASONING_RE.findall(text)
    cleaned = _REASONING_RE.sub("", text).strip()
    # Clean up extra whitespace left by removal
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return [b.strip() for b in blocks], cleaned


def build_reasoning_steps(blocks: list[str]) -> list[ReasoningStep]:
    """Convert raw reasoning blocks into structured steps."""
    steps = []
    for block in blocks:
        step = ReasoningStep(thought=block)
        # Try to parse numbered structure
        lines = block.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith(('选择', '使用', '调用', '执行')):
                step.action = line
            elif line.startswith(('观察', '发现', '注意', '数据')):
                step.observation = line
        steps.append(step)
    return steps


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def _llm_score_confidence(report_text: str, tool_log: list, reasoning_blocks: list) -> Optional[ConfidenceScore]:
    """Use Gemini Flash for confidence scoring."""
    try:
        import google.generativeai as genai
        model = genai.GenerativeModel("gemini-2.0-flash")

        tool_summary = f"{len(tool_log)} tools called" if tool_log else "no tools"
        reasoning_summary = f"{len(reasoning_blocks)} reasoning steps" if reasoning_blocks else "no reasoning"

        prompt = f"""评估以下分析结果的质量。返回JSON对象：
{{
  "overall": 0.0-1.0,
  "data_quality": 0.0-1.0,
  "method_appropriateness": 0.0-1.0,
  "result_completeness": 0.0-1.0,
  "explanation": "简要评估"
}}

分析报告摘要 (前500字):
{report_text[:500]}

执行信息: {tool_summary}, {reasoning_summary}

只返回JSON对象，不要其他文字。"""

        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
        data = json.loads(text)
        return ConfidenceScore(
            overall=float(data.get("overall", 0.5)),
            data_quality=float(data.get("data_quality", 0.5)),
            method_appropriateness=float(data.get("method_appropriateness", 0.5)),
            result_completeness=float(data.get("result_completeness", 0.5)),
            explanation=data.get("explanation", ""),
        )
    except Exception as e:
        logger.debug("LLM confidence scoring failed: %s", e)
        return None


def heuristic_confidence(report_text: str, tool_log: list, error: str = None) -> ConfidenceScore:
    """Heuristic-based confidence scoring (fallback when LLM unavailable)."""
    if error:
        return ConfidenceScore(overall=0.1, explanation=f"Pipeline error: {error[:100]}")

    score = 0.5
    # Boost for longer reports (more analysis done)
    if len(report_text) > 500:
        score += 0.15
    if len(report_text) > 2000:
        score += 0.1
    # Boost for tools used
    tool_count = len(tool_log) if tool_log else 0
    if tool_count > 0:
        score += min(0.15, tool_count * 0.03)
    # Check for error indicators
    error_count = sum(1 for t in (tool_log or []) if t.get("status") == "error")
    if error_count > 0:
        score -= error_count * 0.1

    score = max(0.1, min(1.0, score))
    return ConfidenceScore(
        overall=round(score, 3),
        data_quality=round(score * 0.9, 3),
        method_appropriateness=round(score, 3),
        result_completeness=round(min(1.0, len(report_text) / 1000), 3),
        explanation="Heuristic scoring based on output length, tool usage, and error rate",
    )


def score_confidence(report_text: str, tool_log: list = None,
                     reasoning_blocks: list = None, error: str = None,
                     use_llm: bool = False) -> ConfidenceScore:
    """Score confidence of a pipeline result.

    Uses LLM if available and enabled, falls back to heuristics.
    """
    if use_llm and not error:
        llm_score = _llm_score_confidence(report_text, tool_log or [], reasoning_blocks or [])
        if llm_score:
            return llm_score

    return heuristic_confidence(report_text, tool_log or [], error)
