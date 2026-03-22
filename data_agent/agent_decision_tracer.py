"""
Agent Decision Tracer — records WHY agents made decisions (v15.0).

Complements ProvenancePlugin (records WHAT happened) by capturing the reasoning
behind tool selection, rejection, agent transfers, and quality gate verdicts.
"""

import time
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DecisionEvent:
    """A single decision point during pipeline execution."""
    timestamp: float
    agent_name: str
    event_type: str   # tool_selection / tool_rejection / transfer / quality_gate
    decision: str     # e.g. "选择 spatial_join 进行空间连接"
    reasoning: str    # Why this decision was made
    alternatives: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)


@dataclass
class DecisionTrace:
    """Complete decision trace for a pipeline execution."""
    pipeline_type: str
    trace_id: str
    events: list[DecisionEvent] = field(default_factory=list)

    def add_tool_selection(self, agent_name: str, tool_name: str,
                           reasoning: str = "", alternatives: list[str] = None,
                           args: dict = None):
        self.events.append(DecisionEvent(
            timestamp=time.time(),
            agent_name=agent_name,
            event_type="tool_selection",
            decision=f"选择工具 {tool_name}",
            reasoning=reasoning,
            alternatives=alternatives or [],
            context={"tool": tool_name, "args_keys": list((args or {}).keys())},
        ))

    def add_tool_rejection(self, agent_name: str, tool_name: str, reason: str = ""):
        self.events.append(DecisionEvent(
            timestamp=time.time(),
            agent_name=agent_name,
            event_type="tool_rejection",
            decision=f"拒绝工具 {tool_name}",
            reasoning=reason,
        ))

    def add_agent_transfer(self, from_agent: str, to_agent: str, reason: str = ""):
        self.events.append(DecisionEvent(
            timestamp=time.time(),
            agent_name=from_agent,
            event_type="transfer",
            decision=f"转交 {from_agent} → {to_agent}",
            reasoning=reason,
            context={"from": from_agent, "to": to_agent},
        ))

    def add_quality_gate(self, agent_name: str, verdict: str, feedback: str = ""):
        self.events.append(DecisionEvent(
            timestamp=time.time(),
            agent_name=agent_name,
            event_type="quality_gate",
            decision=f"质量门: {verdict}",
            reasoning=feedback,
            context={"verdict": verdict},
        ))

    def to_dict(self) -> dict:
        return {
            "pipeline_type": self.pipeline_type,
            "trace_id": self.trace_id,
            "event_count": len(self.events),
            "events": [
                {
                    "timestamp": e.timestamp,
                    "agent": e.agent_name,
                    "type": e.event_type,
                    "decision": e.decision,
                    "reasoning": e.reasoning,
                    "alternatives": e.alternatives,
                    "context": e.context,
                }
                for e in self.events
            ],
        }

    def to_mermaid_sequence(self) -> str:
        """Generate a Mermaid sequence diagram from the decision trace."""
        lines = ["sequenceDiagram"]
        lines.append("    participant User")
        agents_seen = set()
        for e in self.events:
            if e.agent_name not in agents_seen:
                lines.append(f"    participant {e.agent_name}")
                agents_seen.add(e.agent_name)

        prev_agent = "User"
        for e in self.events:
            if e.event_type == "transfer":
                from_a = e.context.get("from", prev_agent)
                to_a = e.context.get("to", e.agent_name)
                lines.append(f"    {from_a}->>+{to_a}: {e.decision}")
                prev_agent = to_a
            elif e.event_type == "tool_selection":
                tool = e.context.get("tool", "tool")
                lines.append(f"    {e.agent_name}->>+{e.agent_name}: {tool}")
                if e.reasoning:
                    lines.append(f"    Note over {e.agent_name}: {e.reasoning[:50]}")
            elif e.event_type == "quality_gate":
                verdict = e.context.get("verdict", "")
                lines.append(f"    {e.agent_name}-->>-{e.agent_name}: {verdict}")

        return "\n".join(lines)
