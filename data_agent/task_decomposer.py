"""
Intelligent Task Decomposition (v9.0.4).

Decomposes complex user requests into a structured DAG of sub-tasks,
then builds an execution plan using ParallelAgent for independent tasks.

Components:
- ``TaskNode`` / ``TaskGraph``: DAG data structures with topological sort
- ``decompose_task()``: LLM-based request decomposition
- ``build_parallel_execution_plan()``: Wave-based parallel execution plan

Usage::

    from data_agent.task_decomposer import decompose_task, build_parallel_execution_plan
    graph = await decompose_task("分析土地利用变化并生成报告", available_agents)
    waves = build_parallel_execution_plan(graph)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("data_agent.task_decomposer")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TaskNode:
    """A single sub-task in the decomposition graph."""
    id: str
    description: str
    agent_hint: str = ""  # Suggested agent name
    dependencies: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed

    def __hash__(self):
        return hash(self.id)


class TaskGraph:
    """Directed acyclic graph of TaskNodes with topological sort and cycle detection."""

    def __init__(self):
        self.nodes: dict[str, TaskNode] = {}

    def add_node(self, node: TaskNode) -> None:
        self.nodes[node.id] = node

    def get_node(self, node_id: str) -> TaskNode | None:
        return self.nodes.get(node_id)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    def has_cycle(self) -> bool:
        """Detect cycles using DFS coloring."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in self.nodes}

        def _dfs(nid: str) -> bool:
            color[nid] = GRAY
            node = self.nodes[nid]
            for dep in node.dependencies:
                if dep not in color:
                    continue
                if color[dep] == GRAY:
                    return True  # Back edge → cycle
                if color[dep] == WHITE and _dfs(dep):
                    return True
            color[nid] = BLACK
            return False

        return any(color[nid] == WHITE and _dfs(nid) for nid in self.nodes)

    def topological_sort(self) -> list[str]:
        """Kahn's algorithm — returns node IDs in topological order.

        Raises ValueError if the graph has a cycle.
        """
        if self.has_cycle():
            raise ValueError("TaskGraph contains a cycle")

        in_degree = {nid: 0 for nid in self.nodes}
        for node in self.nodes.values():
            for dep in node.dependencies:
                if dep in in_degree:
                    in_degree[dep] += 1

        # Wait — in_degree should count how many *depend on* this node,
        # but for Kahn's we need: in_degree[n] = how many nodes n depends on
        # Let me recalculate correctly.
        in_degree = {nid: 0 for nid in self.nodes}
        for node in self.nodes.values():
            for dep in node.dependencies:
                if dep in self.nodes:
                    in_degree[node.id] += 1

        # Start with nodes that have no dependencies
        # Actually, simpler: in_degree[node.id] = len(valid deps)
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []
        completed = set()

        while queue:
            nid = queue.pop(0)
            result.append(nid)
            completed.add(nid)
            # Find nodes whose dependencies are now all completed
            for candidate_id, candidate in self.nodes.items():
                if candidate_id in completed:
                    continue
                if candidate_id in [x for x in queue]:
                    continue
                if all(d in completed for d in candidate.dependencies if d in self.nodes):
                    if candidate_id not in result:
                        queue.append(candidate_id)

        return result

    def get_execution_waves(self) -> list[list[str]]:
        """Group tasks into waves — tasks in the same wave can run in parallel.

        Each wave contains tasks whose dependencies are all in earlier waves.
        """
        if self.has_cycle():
            raise ValueError("TaskGraph contains a cycle")

        completed = set()
        waves = []
        remaining = set(self.nodes.keys())

        while remaining:
            # Find all tasks whose dependencies are completed
            wave = []
            for nid in remaining:
                node = self.nodes[nid]
                deps_in_graph = [d for d in node.dependencies if d in self.nodes]
                if all(d in completed for d in deps_in_graph):
                    wave.append(nid)
            if not wave:
                # Safety: shouldn't happen if no cycle, but break infinite loop
                break
            waves.append(sorted(wave))
            completed.update(wave)
            remaining -= set(wave)

        return waves


# ---------------------------------------------------------------------------
# LLM-based decomposition
# ---------------------------------------------------------------------------

_DECOMPOSE_PROMPT = """你是一个任务分解专家。将用户的复杂请求分解为可执行的子任务。

可用的 Agent 类型：
{agent_list}

请将以下请求分解为子任务，输出 JSON 数组：
[
  {{"id": "t1", "description": "子任务描述", "agent_hint": "建议的Agent名", "dependencies": []}},
  {{"id": "t2", "description": "子任务描述", "agent_hint": "建议的Agent名", "dependencies": ["t1"]}}
]

规则：
1. 每个子任务必须有唯一 id (t1, t2, ...)
2. dependencies 列出必须先完成的任务 id
3. agent_hint 从可用 Agent 列表中选择
4. 保持子任务数量在 2-6 个
5. 独立的任务不要添加不必要的依赖

用户请求: {query}
"""


async def decompose_task(
    query: str,
    available_agents: list[str] | None = None,
) -> TaskGraph:
    """Decompose a user query into a TaskGraph using LLM.

    Args:
        query: User's natural language request.
        available_agents: List of available agent names.

    Returns:
        TaskGraph with decomposed sub-tasks.
    """
    if available_agents is None:
        available_agents = [
            "DataExploration", "DataProcessing", "DataAnalysis",
            "DataVisualization", "DataSummary", "PlannerReporter",
        ]

    agent_list = "\n".join(f"- {a}" for a in available_agents)
    prompt = _DECOMPOSE_PROMPT.format(agent_list=agent_list, query=query)

    try:
        response_text = await _call_llm(prompt)
        tasks = _parse_decomposition(response_text)
    except Exception as e:
        logger.warning("Task decomposition failed (%s), using single-task fallback", e)
        tasks = [{"id": "t1", "description": query, "agent_hint": "", "dependencies": []}]

    graph = TaskGraph()
    for t in tasks:
        node = TaskNode(
            id=t.get("id", f"t{len(graph.nodes) + 1}"),
            description=t.get("description", ""),
            agent_hint=t.get("agent_hint", ""),
            dependencies=t.get("dependencies", []),
        )
        graph.add_node(node)

    # Validate: remove cycles by dropping back-edges
    if graph.has_cycle():
        logger.warning("Decomposition produced a cycle — removing edges")
        _remove_cycles(graph)

    return graph


async def _call_llm(prompt: str) -> str:
    """Call Gemini Flash for task decomposition."""
    try:
        import google.genai as genai
        client = genai.Client()
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text or ""
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        raise


def _parse_decomposition(text: str) -> list[dict]:
    """Extract JSON task list from LLM response text."""
    # Try to find JSON array in the response
    import re
    # Look for [...] pattern
    match = re.search(r'\[[\s\S]*\]', text)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list) and len(result) > 0:
                return result
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse decomposition from LLM response: {text[:200]}")


def _remove_cycles(graph: TaskGraph) -> None:
    """Remove back-edges to break cycles (greedy)."""
    for node in graph.nodes.values():
        valid_deps = []
        for dep in node.dependencies:
            node.dependencies = valid_deps + [dep]
            if graph.has_cycle():
                # This dep creates a cycle — skip it
                node.dependencies = valid_deps
            else:
                valid_deps.append(dep)
        node.dependencies = valid_deps


# ---------------------------------------------------------------------------
# Execution plan builder
# ---------------------------------------------------------------------------

def build_parallel_execution_plan(graph: TaskGraph) -> list[list[TaskNode]]:
    """Convert a TaskGraph into waves of parallel-executable TaskNodes.

    Returns:
        List of waves, where each wave is a list of TaskNodes that
        can execute concurrently.
    """
    waves_ids = graph.get_execution_waves()
    return [[graph.nodes[nid] for nid in wave] for wave in waves_ids]


# ---------------------------------------------------------------------------
# Subtask preview & sequential execution (v23.0 — Intent Disambiguation v2)
# ---------------------------------------------------------------------------

def format_subtask_preview(graph: TaskGraph) -> str:
    """Format a TaskGraph into a human-readable subtask list for user confirmation.

    Returns markdown text showing numbered subtasks with dependencies.
    """
    waves = graph.get_execution_waves()
    lines: list[str] = []
    for node in graph.nodes.values():
        deps = f" (依赖: {', '.join(node.dependencies)})" if node.dependencies else ""
        hint = f" [{node.agent_hint}]" if node.agent_hint else ""
        lines.append(f"  {node.id}. {node.description}{hint}{deps}")
    lines.append(f"\n共 {graph.node_count} 步，{len(waves)} 批次执行")
    return "\n".join(lines)


async def execute_task_graph(
    graph: TaskGraph,
    execute_fn,
    on_progress=None,
) -> list[dict[str, Any]]:
    """Execute subtasks wave-by-wave, calling *execute_fn* for each node.

    Args:
        graph: The decomposed TaskGraph.
        execute_fn: ``async def(node: TaskNode, context: dict) -> str``
            Runs a single subtask, returns the result text.
        on_progress: Optional ``async def(node: TaskNode, status: str, result: str)``
            Called when a subtask starts/completes/fails.

    Returns:
        List of dicts ``{"id", "description", "status", "result"}``.
    """
    import asyncio

    waves = build_parallel_execution_plan(graph)
    results: list[dict[str, Any]] = []
    context: dict[str, Any] = {}  # shared context across subtasks

    for wave_idx, wave in enumerate(waves):
        async def _run_node(node: TaskNode):
            node.status = "running"
            if on_progress:
                await on_progress(node, "running", "")
            try:
                result_text = await execute_fn(node, context)
                node.status = "completed"
                context[node.id] = result_text
                if on_progress:
                    await on_progress(node, "completed", result_text)
                return {"id": node.id, "description": node.description,
                        "status": "completed", "result": result_text}
            except Exception as e:
                node.status = "failed"
                err = str(e)
                if on_progress:
                    await on_progress(node, "failed", err)
                return {"id": node.id, "description": node.description,
                        "status": "failed", "result": err}

        if len(wave) == 1:
            results.append(await _run_node(wave[0]))
        else:
            wave_results = await asyncio.gather(*[_run_node(n) for n in wave])
            results.extend(wave_results)

    return results
