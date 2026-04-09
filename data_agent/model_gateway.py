"""
Model Gateway — Unified online/offline model routing with cost attribution.

Supports three model backends:
- **gemini**: Google Gemini API (online, default)
- **litellm**: Any LiteLLM-compatible model (OpenAI, Anthropic, local, etc.)
- **lm_studio**: Local models via LM Studio OpenAI-compatible API (offline)

Models are registered in ModelRegistry with backend metadata.  The
``create_model()`` factory returns the appropriate ADK model wrapper
(``Gemini`` or ``LiteLlm``) based on the backend field.

Environment variables:
- MODEL_FAST / MODEL_STANDARD / MODEL_PREMIUM — tier defaults
- LM_STUDIO_BASE_URL — LM Studio endpoint (default http://localhost:1234/v1)
- LM_STUDIO_MODEL — default local model name (default gemma-3-4b)
- MODEL_BACKEND — global default backend: gemini | litellm (default gemini)
"""
import os

from .observability import get_logger

logger = get_logger("model_gateway")


# =====================================================================
# Model Registry — unified online + offline model catalog
# =====================================================================

class ModelRegistry:
    """Registry of available models with metadata.

    Each model entry contains:
    - backend: "gemini" | "litellm" | "lm_studio"
    - tier: "fast" | "standard" | "premium" | "local"
    - api_base: (optional) override API endpoint for local models
    - cost_per_1k_input / output: pricing for cost tracking
    - max_context_tokens: context window limit
    - capabilities: list of task types the model supports
    - online: whether the model requires internet connectivity
    """

    # Built-in model definitions
    _builtin_models = {
        # --- Online: Google Gemini ---
        "gemini-2.0-flash": {
            "backend": "gemini",
            "tier": "fast",
            "online": True,
            "cost_per_1k_input": 0.10,
            "cost_per_1k_output": 0.40,
            "latency_p50_ms": 800,
            "max_context_tokens": 1_000_000,
            "capabilities": ["classification", "extraction", "summarization"],
        },
        "gemini-2.5-flash": {
            "backend": "gemini",
            "tier": "standard",
            "online": True,
            "cost_per_1k_input": 0.15,
            "cost_per_1k_output": 0.60,
            "latency_p50_ms": 1200,
            "max_context_tokens": 2_000_000,
            "capabilities": ["reasoning", "analysis", "generation", "classification"],
        },
        "gemini-2.5-pro": {
            "backend": "gemini",
            "tier": "premium",
            "online": True,
            "cost_per_1k_input": 1.25,
            "cost_per_1k_output": 5.00,
            "latency_p50_ms": 2500,
            "max_context_tokens": 2_000_000,
            "capabilities": ["complex_reasoning", "planning", "coding", "analysis"],
        },
        # --- Offline: LM Studio local models ---
        "gemma-3-4b": {
            "backend": "lm_studio",
            "tier": "local",
            "online": False,
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "latency_p50_ms": 2000,
            "max_context_tokens": 128_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "analysis", "generation"],
        },
        # --- Online: Gemma 4 via Gemini API (v23.0) ---
        "gemma-4-31b-it": {
            "backend": "gemini",
            "tier": "standard",
            "online": True,
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "latency_p50_ms": 1500,
            "max_context_tokens": 256_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "analysis", "generation", "coding"],
        },
    }

    # Mutable registry: starts with builtins, can be extended at runtime
    models: dict[str, dict] = {}

    @classmethod
    def _ensure_initialized(cls):
        if not cls.models:
            cls.models = dict(cls._builtin_models)
            # Auto-register LM Studio model from env var
            lm_model = os.environ.get("LM_STUDIO_MODEL")
            if lm_model and lm_model not in cls.models:
                cls.register_model(lm_model, backend="lm_studio", tier="local")

    @classmethod
    def register_model(cls, name: str, *, backend: str = "litellm",
                       tier: str = "standard", online: bool | None = None,
                       api_base: str | None = None,
                       max_context_tokens: int = 128_000,
                       capabilities: list[str] | None = None,
                       cost_per_1k_input: float = 0.0,
                       cost_per_1k_output: float = 0.0,
                       **extra):
        """Register a new model at runtime.

        Args:
            name: Model identifier (e.g. "openai/gpt-4o", "ollama/llama3").
            backend: "gemini", "litellm", or "lm_studio".
            tier: "fast", "standard", "premium", or "local".
            api_base: Override API endpoint (e.g. "http://localhost:1234/v1").
            online: Whether internet is required (auto-detected from backend).
        """
        cls._ensure_initialized()
        if online is None:
            online = (backend not in ("lm_studio", "ollama")
                      and not name.startswith("ollama/"))
        entry = {
            "backend": backend,
            "tier": tier,
            "online": online,
            "cost_per_1k_input": cost_per_1k_input,
            "cost_per_1k_output": cost_per_1k_output,
            "latency_p50_ms": extra.get("latency_p50_ms", 2000),
            "max_context_tokens": max_context_tokens,
            "capabilities": capabilities or [
                "classification", "extraction", "summarization",
                "reasoning", "analysis", "generation",
            ],
        }
        if api_base:
            entry["api_base"] = api_base
        # v23.0: Store extra LiteLLM params (for vLLM endpoints)
        for k in ("extra_headers", "extra_body", "api_key_env", "model_id"):
            if k in extra:
                entry[k] = extra[k]
        cls.models[name] = entry
        logger.info(f"Registered model: {name} (backend={backend}, tier={tier})")

    @classmethod
    def load_from_yaml(cls, path: str = None) -> int:
        """Load model definitions from YAML config file (v20.0).

        Args:
            path: Path to models.yaml. Defaults to conf/models.yaml next to this module.

        Returns:
            Number of models loaded from YAML.
        """
        import os
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "conf", "models.yaml")
        if not os.path.exists(path):
            return 0
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            if not config or "models" not in config:
                return 0
            count = 0
            for name, spec in config["models"].items():
                if name in cls.models:
                    continue  # don't overwrite built-in defaults
                backend = spec.get("backend", "litellm")
                cls.register_model(
                    name,
                    backend=backend,
                    tier=spec.get("tier", "standard"),
                    api_base=spec.get("base_url"),
                    max_context_tokens=spec.get("context_tokens", 128_000),
                    capabilities=spec.get("capabilities"),
                    cost_per_1k_input=spec.get("cost_per_1k_input", 0.0),
                    cost_per_1k_output=spec.get("cost_per_1k_output", 0.0),
                    # v23.0: Pass through extra LiteLLM params
                    model_id=spec.get("model_id"),
                    api_key_env=spec.get("api_key_env"),
                    extra_headers=spec.get("extra_headers"),
                    extra_body=spec.get("extra_body"),
                )
                count += 1
            if count:
                logger.info("Loaded %d model(s) from YAML: %s", count, path)
            return count
        except Exception as e:
            logger.warning("Failed to load models YAML: %s", e)
            return 0

    @classmethod
    def unregister_model(cls, name: str):
        """Remove a model from the registry."""
        cls._ensure_initialized()
        cls.models.pop(name, None)

    @classmethod
    def get_model_info(cls, model_name: str) -> dict:
        """Get model metadata."""
        cls._ensure_initialized()
        return cls.models.get(model_name, {})

    @classmethod
    def list_models(cls, online_only: bool = False,
                    offline_only: bool = False) -> list[dict]:
        """List all registered models with metadata.

        Args:
            online_only: Filter to online models only.
            offline_only: Filter to offline/local models only.
        """
        cls._ensure_initialized()
        result = []
        for k, v in cls.models.items():
            if online_only and not v.get("online", True):
                continue
            if offline_only and v.get("online", True):
                continue
            result.append({"name": k, **v})
        return result

    @classmethod
    def get_offline_models(cls) -> list[str]:
        """Return names of all offline/local models."""
        cls._ensure_initialized()
        return [k for k, v in cls.models.items() if not v.get("online", True)]

    @classmethod
    def get_online_models(cls) -> list[str]:
        """Return names of all online models."""
        cls._ensure_initialized()
        return [k for k, v in cls.models.items() if v.get("online", True)]

    @classmethod
    def reset(cls):
        """Reset registry to builtins (for testing)."""
        cls.models = {}


# =====================================================================
# Model Factory — create ADK model instances
# =====================================================================

def _get_lm_studio_base_url() -> str:
    """Get LM Studio API base URL from env var."""
    return os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")


def create_model(model_name: str):
    """Create an ADK-compatible model instance for the given model name.

    Automatically selects the correct backend wrapper:
    - Gemini models → google.adk.models.google_llm.Gemini
    - LiteLLM/LM Studio models → google.adk.models.lite_llm.LiteLlm

    For LM Studio models, the OpenAI-compatible API base URL is set
    via the LM_STUDIO_BASE_URL environment variable.

    Returns:
        BaseLlm instance (Gemini or LiteLlm).
    """
    ModelRegistry._ensure_initialized()
    info = ModelRegistry.get_model_info(model_name)
    backend = info.get("backend", _detect_backend(model_name))

    if backend == "gemini":
        return _create_gemini_model(model_name)
    elif backend == "lm_studio":
        return _create_lm_studio_model(model_name, info)
    else:
        # Generic LiteLLM — supports openai/, anthropic/, ollama/, etc.
        return _create_litellm_model(model_name, info)


def _detect_backend(model_name: str) -> str:
    """Infer backend from model name prefix when not in registry."""
    if model_name.startswith("gemini"):
        return "gemini"
    if model_name.startswith("gemma-"):
        return "gemini"  # Gemma models via Gemini API
    if "/" in model_name:
        # e.g. "openai/gpt-4o", "anthropic/claude-3", "ollama/llama3"
        return "litellm"
    # Default to Gemini for backward compatibility
    default = os.environ.get("MODEL_BACKEND", "gemini")
    return default


def _create_gemini_model(model_name: str):
    """Create a Gemini model with retry configuration."""
    from google.adk.models.google_llm import Gemini
    from google.genai import types
    return Gemini(
        model=model_name,
        retry_options=types.HttpRetryOptions(
            initial_delay=2.0,
            attempts=3,
        ),
    )


def _create_lm_studio_model(model_name: str, info: dict):
    """Create a LiteLLM model pointing to LM Studio's OpenAI-compatible API."""
    from google.adk.models.lite_llm import LiteLlm

    api_base = info.get("api_base", _get_lm_studio_base_url())

    # LiteLLM uses "openai/" prefix for OpenAI-compatible endpoints
    litellm_name = f"openai/{model_name}" if "/" not in model_name else model_name

    # Set env vars that litellm needs
    os.environ.setdefault("OPENAI_API_KEY", "lm-studio")
    os.environ["OPENAI_API_BASE"] = api_base

    return LiteLlm(model=litellm_name)


def _create_litellm_model(model_name: str, info: dict):
    """Create a generic LiteLLM model.

    v23.0: Supports extra_headers and extra_body for vLLM endpoints
    (e.g. Gemma 4 self-hosted with enable_thinking).
    """
    from google.adk.models.lite_llm import LiteLlm

    api_base = info.get("api_base")
    if api_base:
        # Provider-specific env var handling
        if model_name.startswith("openai/"):
            os.environ["OPENAI_API_BASE"] = api_base
        elif model_name.startswith("ollama/"):
            os.environ["OLLAMA_API_BASE"] = api_base

    # Use model_id override if specified (e.g. "openai/google/gemma-4-31B-it")
    effective_name = info.get("model_id", model_name)

    # Set API key from env var name if specified
    api_key_env = info.get("api_key_env")
    if api_key_env:
        api_key = os.environ.get(api_key_env, "")
        if api_key and model_name.startswith("openai/"):
            os.environ["OPENAI_API_KEY"] = api_key

    return LiteLlm(model=effective_name)


# =====================================================================
# Model Router — task-aware selection with online/offline awareness
# =====================================================================

class ModelRouter:
    """Task-aware model selection with online/offline support."""

    def route(self, task_type: str = None, context_tokens: int = 0,
              quality_requirement: str = "standard",
              budget_per_call_usd: float = None,
              prefer_offline: bool = False) -> str:
        """Select optimal model based on constraints.

        Args:
            task_type: Task capability required (e.g. "reasoning", "planning").
            context_tokens: Estimated context size.
            quality_requirement: "fast", "standard", "premium", or "local".
            budget_per_call_usd: Max cost per call.
            prefer_offline: Prefer local models when available.

        Returns: model_name string.
        """
        ModelRegistry._ensure_initialized()
        candidates = list(ModelRegistry.models.keys())

        # If explicitly requesting local tier, filter to offline only
        if quality_requirement == "local":
            candidates = [m for m in candidates
                          if not ModelRegistry.models[m].get("online", True)]
            if not candidates:
                logger.warning("No offline models available, falling back to standard")
                return os.environ.get("MODEL_STANDARD", "gemini-2.5-flash")
            return candidates[0]

        # Filter by context size
        if context_tokens > 0:
            candidates = [
                m for m in candidates
                if ModelRegistry.models[m]["max_context_tokens"] >= context_tokens
            ]

        # Filter by capability
        if task_type:
            capable = [
                m for m in candidates
                if task_type in ModelRegistry.models[m].get("capabilities", [])
            ]
            if capable:
                candidates = capable

        # Filter by budget
        if budget_per_call_usd is not None:
            candidates = [
                m for m in candidates
                if self._estimate_cost(m, 2000, 500) <= budget_per_call_usd
            ]

        # Prefer offline if requested and available
        if prefer_offline:
            offline = [m for m in candidates
                       if not ModelRegistry.models[m].get("online", True)]
            if offline:
                candidates = offline

        if not candidates:
            fallback = os.environ.get("MODEL_STANDARD", "gemini-2.5-flash")
            logger.warning(f"No models match constraints, falling back to {fallback}")
            return fallback

        # Select by quality tier
        tier_preference = {"fast": 0, "standard": 1, "premium": 2, "local": 0}
        target_tier = tier_preference.get(quality_requirement, 1)

        best = min(candidates, key=lambda m: abs(
            tier_preference.get(ModelRegistry.models[m]["tier"], 1) - target_tier
        ))

        logger.info(f"Routed to {best} (task={task_type}, quality={quality_requirement}, "
                     f"offline={prefer_offline})")
        return best

    def _estimate_cost(self, model_name: str, input_tokens: int,
                       output_tokens: int) -> float:
        """Estimate cost for a model call."""
        info = ModelRegistry.models.get(model_name, {})
        return (input_tokens * info.get("cost_per_1k_input", 0) +
                output_tokens * info.get("cost_per_1k_output", 0)) / 1000
