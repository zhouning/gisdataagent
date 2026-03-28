"""
Model Gateway - Task-aware model routing with cost attribution.
Extends existing MODEL_TIER_MAP with capability metadata.
"""
from .observability import get_logger

logger = get_logger("model_gateway")


class ModelRegistry:
    """Registry of available models with metadata"""

    models = {
        "gemini-2.0-flash": {
            "tier": "fast",
            "cost_per_1k_input": 0.10,
            "cost_per_1k_output": 0.40,
            "latency_p50_ms": 800,
            "max_context_tokens": 1000000,
            "capabilities": ["classification", "extraction", "summarization"],
        },
        "gemini-2.5-flash": {
            "tier": "standard",
            "cost_per_1k_input": 0.15,
            "cost_per_1k_output": 0.60,
            "latency_p50_ms": 1200,
            "max_context_tokens": 2000000,
            "capabilities": ["reasoning", "analysis", "generation", "classification"],
        },
        "gemini-2.5-pro": {
            "tier": "premium",
            "cost_per_1k_input": 1.25,
            "cost_per_1k_output": 5.00,
            "latency_p50_ms": 2500,
            "max_context_tokens": 2000000,
            "capabilities": ["complex_reasoning", "planning", "coding", "analysis"],
        },
    }

    @classmethod
    def get_model_info(cls, model_name: str) -> dict:
        """Get model metadata"""
        return cls.models.get(model_name, {})

    @classmethod
    def list_models(cls) -> list[dict]:
        """List all models with metadata"""
        return [{"name": k, **v} for k, v in cls.models.items()]


class ModelRouter:
    """Task-aware model selection"""

    def route(self, task_type: str = None, context_tokens: int = 0,
              quality_requirement: str = "standard",
              budget_per_call_usd: float = None) -> str:
        """Select optimal model based on constraints. Returns: model_name"""
        candidates = list(ModelRegistry.models.keys())

        # Filter by context size
        if context_tokens > 0:
            candidates = [
                m for m in candidates
                if ModelRegistry.models[m]["max_context_tokens"] >= context_tokens
            ]

        # Filter by capability
        if task_type:
            candidates = [
                m for m in candidates
                if task_type in ModelRegistry.models[m]["capabilities"]
            ]

        # Filter by budget
        if budget_per_call_usd:
            candidates = [
                m for m in candidates
                if self._estimate_cost(m, 2000, 500) <= budget_per_call_usd
            ]

        if not candidates:
            logger.warning("No models match constraints, falling back to standard")
            return "gemini-2.5-flash"

        # Select by quality tier
        tier_preference = {"fast": 0, "standard": 1, "premium": 2}
        target_tier = tier_preference.get(quality_requirement, 1)

        best = min(candidates, key=lambda m: abs(
            tier_preference.get(ModelRegistry.models[m]["tier"], 1) - target_tier
        ))

        logger.info(f"Routed to {best} (task={task_type}, quality={quality_requirement})")
        return best

    def _estimate_cost(self, model_name: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a model"""
        info = ModelRegistry.models[model_name]
        return (input_tokens * info["cost_per_1k_input"] +
                output_tokens * info["cost_per_1k_output"]) / 1000
