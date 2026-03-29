"""
Context Manager - Pluggable context providers with token budget.
Orchestrates semantic layer, KB, standards, and case library.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from .observability import get_logger

logger = get_logger("context_manager")


@dataclass
class ContextBlock:
    """Single unit of context"""
    source: str
    content: str
    token_count: int
    relevance_score: float
    compressible: bool = True


class ContextProvider(ABC):
    """Base class for context providers"""

    @abstractmethod
    def get_context(self, task_type: str, step: str,
                    user_context: dict) -> list[ContextBlock]:
        pass


class SemanticProvider(ContextProvider):
    """Wraps existing semantic_layer.py"""

    def get_context(self, task_type, step, user_context):
        try:
            from .semantic_layer import resolve_semantic_context
            import json
            query = user_context.get("query", "")
            if not query:
                return []
            semantic = resolve_semantic_context(query)
            content = json.dumps(semantic, ensure_ascii=False)
            return [ContextBlock(
                source="semantic_layer",
                content=content,
                token_count=len(content) // 4,
                relevance_score=1.0,
                compressible=False
            )]
        except Exception as e:
            logger.warning(f"SemanticProvider failed: {e}")
            return []


class ContextManager:
    """Orchestrates all providers with token budget"""

    def __init__(self, max_tokens: int = 100000):
        self.max_tokens = max_tokens
        self.providers = {}

    def register_provider(self, name: str, provider: ContextProvider):
        self.providers[name] = provider

    def prepare(self, task_type: str, step: str,
                user_context: dict) -> list[ContextBlock]:
        """Collect context from all providers, sort by relevance, enforce token budget."""
        candidates = []
        for name, provider in self.providers.items():
            try:
                blocks = provider.get_context(task_type, step, user_context)
                candidates.extend(blocks)
            except Exception as e:
                logger.warning(f"Provider {name} failed: {e}")

        candidates.sort(key=lambda b: b.relevance_score, reverse=True)

        selected = []
        budget = self.max_tokens
        for block in candidates:
            if block.token_count <= budget:
                selected.append(block)
                budget -= block.token_count

        logger.info(f"Selected {len(selected)} context blocks, {self.max_tokens - budget} tokens")
        return selected

    def format_context(self, blocks: list[ContextBlock]) -> str:
        """Format blocks into prompt-ready text"""
        if not blocks:
            return ""
        sections = []
        for block in blocks:
            sections.append(f"[{block.source}]\n{block.content}\n")
        return "\n".join(sections)
