"""
Model Gateway — Unified online/offline model routing with cost attribution.

Supports four model backends:
- **gemini**: Google Gemini API (online, default)
- **deepseek**: DeepSeek API via LiteLLM provider (online)
- **litellm**: Any LiteLLM-compatible model (OpenAI, Anthropic, local, etc.)
- **lm_studio**: Local models via LM Studio OpenAI-compatible API (offline)

Models are registered in ModelRegistry with backend metadata.  The
``create_model()`` factory returns the appropriate ADK model wrapper
(``Gemini`` or ``LiteLlm``) based on the backend field.

Environment variables:
- MODEL_FAST / MODEL_STANDARD / MODEL_PREMIUM — tier defaults
- LM_STUDIO_BASE_URL — LM Studio endpoint (default http://localhost:1234/v1)
- LM_STUDIO_MODEL — default local model name (default gemma-3-4b)
- MODEL_BACKEND — global default backend: gemini | deepseek | litellm | lm_studio (default gemini)
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
    - backend: "gemini" | "deepseek" | "litellm" | "lm_studio"
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
        # --- Online: DeepSeek v4 ---
        "deepseek-v4-flash": {
            "backend": "deepseek",
            "tier": "fast",
            "online": True,
            "cost_per_1k_input": 1.0 / 1000,
            "cost_per_1k_output": 2.0 / 1000,
            "latency_p50_ms": 900,
            "max_context_tokens": 1_000_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "analysis", "generation"],
            "api_base": "https://api.deepseek.com",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model_id": "openai/deepseek-v4-flash",
        },
        "deepseek-v4-pro": {
            "backend": "deepseek",
            "tier": "premium",
            "online": True,
            "cost_per_1k_input": 12.0 / 1000,
            "cost_per_1k_output": 24.0 / 1000,
            "latency_p50_ms": 2000,
            "max_context_tokens": 1_000_000,
            "capabilities": ["complex_reasoning", "planning", "coding",
                             "analysis", "generation"],
            "api_base": "https://api.deepseek.com",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model_id": "openai/deepseek-v4-pro",
        },
        # --- Online: Qwen via Aliyun token-plan MaaS (OpenAI-compatible endpoint) ---
        # The token-plan MaaS service at token-plan.cn-beijing.maas.aliyuncs.com
        # speaks OpenAI Chat Completions spec, so LiteLLM routes through the
        # `openai/` prefix same as DeepSeek. Requires DASHSCOPE_API_KEY in env
        # (historical name; the token-plan key is stored under it).
        "qwen3.6-flash": {
            "backend": "qwen",
            "tier": "fast",
            "online": True,
            "cost_per_1k_input": 0.5 / 1000,
            "cost_per_1k_output": 1.5 / 1000,
            "latency_p50_ms": 1000,
            "max_context_tokens": 1_000_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "analysis", "generation"],
            "api_base": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "api_key_env": "DASHSCOPE_API_KEY",
            "model_id": "openai/qwen3.6-flash",
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
        # --- Online: Gemini 3.x preview (v7 2026-05-12) ---
        # 3.x is the next generation after 2.5; API model ids use the
        # `-preview` suffix while in public preview.
        "gemini-3-flash-preview": {
            "backend": "gemini",
            "tier": "standard",
            "online": True,
            "cost_per_1k_input": 0.20,
            "cost_per_1k_output": 0.80,
            "latency_p50_ms": 1200,
            "max_context_tokens": 2_000_000,
            "capabilities": ["reasoning", "analysis", "generation",
                             "classification", "coding"],
        },
        "gemini-3.1-pro-preview": {
            "backend": "gemini",
            "tier": "premium",
            "online": True,
            "cost_per_1k_input": 1.50,
            "cost_per_1k_output": 6.00,
            "latency_p50_ms": 2500,
            "max_context_tokens": 2_000_000,
            "capabilities": ["complex_reasoning", "planning", "coding",
                             "analysis", "generation"],
        },
        # Gemini 3.1 Flash-Lite preview — high-volume / low-latency tier in
        # the 3.1 family. Published pricing places it below Flash / Pro while
        # retaining function-calling and 1M-token context (per ai.google.dev
        # model docs, 2026-05).
        "gemini-3.1-flash-lite-preview": {
            "backend": "gemini",
            "tier": "fast",
            "online": True,
            "cost_per_1k_input": 0.10,
            "cost_per_1k_output": 0.40,
            "latency_p50_ms": 700,
            "max_context_tokens": 1_000_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "generation", "coding"],
        },
        # Gemini 3.5 Flash — GA 2026-05-19 at Google I/O 2026. Replaces
        # gemini-3-flash-preview; the preview id now points at the prior
        # generation. Pricing $1.50 / $9.00 per 1M tokens (input/output),
        # 1M input context / 64K output. Dynamic thinking ON by default
        # (thinking_level=medium); temperature/top_p/top_k are no longer
        # recommended in config but still accepted. Knowledge cutoff Jan 2026.
        "gemini-3.5-flash": {
            "backend": "gemini",
            "tier": "standard",
            "online": True,
            "cost_per_1k_input": 1.50 / 1000,
            "cost_per_1k_output": 9.00 / 1000,
            "latency_p50_ms": 1500,
            "max_context_tokens": 1_048_576,
            "capabilities": ["reasoning", "analysis", "generation",
                             "classification", "coding", "complex_reasoning"],
        },
        # --- Online: Qwen 3.6 plus via Aliyun token-plan MaaS ---
        # 'plus' is the higher-quality tier in the Qwen MaaS hierarchy
        # (flash < plus < max). Same endpoint as qwen3.6-flash.
        "qwen3.6-plus": {
            "backend": "qwen",
            "tier": "premium",
            "online": True,
            "cost_per_1k_input": 4.0 / 1000,
            "cost_per_1k_output": 12.0 / 1000,
            "latency_p50_ms": 1800,
            "max_context_tokens": 1_000_000,
            "capabilities": ["complex_reasoning", "planning", "coding",
                             "analysis", "generation"],
            "api_base": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "api_key_env": "DASHSCOPE_API_KEY",
            "model_id": "openai/qwen3.6-plus",
        },
        # --- Online: Qwen 3.7 Max via Aliyun token-plan MaaS (2026-05-21 GA) ---
        # Flagship model for agent workloads (Terminal-Bench 2.0 = 69.7,
        # 35-hour autonomous runs with 1000+ tool calls per Alibaba). Top
        # tier in the Qwen MaaS hierarchy (flash < plus < max). Same
        # OpenAI-compatible endpoint as qwen3.6-flash/plus. Same NO_PROXY
        # bypass via _create_qwen_model.
        "qwen3.7-max": {
            "backend": "qwen",
            "tier": "premium",
            "online": True,
            "cost_per_1k_input": 12.0 / 1000,
            "cost_per_1k_output": 36.0 / 1000,
            "latency_p50_ms": 2500,
            "max_context_tokens": 1_000_000,
            "capabilities": ["complex_reasoning", "planning", "coding",
                             "analysis", "generation"],
            "api_base": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "api_key_env": "DASHSCOPE_API_KEY",
            "model_id": "openai/qwen3.7-max",
        },
        # --- Local: Gemma 4 via Ollama (v6 Phase 3) ---
        # AI Studio's 16K input-TPM ceiling makes agent-loop NL2SQL impractical
        # for Gemma; the local Ollama deployment removes the rate limit. ADK
        # Ollama integration uses LiteLLM with the `ollama_chat/` prefix
        # (NOT `ollama/` — the latter causes infinite tool-call loops per ADK
        # docs at https://adk.wiki/agents/models/ollama/).
        #
        # The api_base default below is the host-loopback for native macOS dev;
        # K8s overlays set OLLAMA_API_BASE=http://ollama:11434 (ExternalName
        # Service pointing at host.docker.internal). The override loop in
        # _ensure_initialized() rewrites api_base on this entry at startup.
        #
        # `model_id` MUST match the tag served by the host Ollama exactly
        # (case-sensitive). Verify with `curl localhost:11434/api/tags`.
        "gemma4-26b-ollama": {
            "backend": "litellm",
            "tier": "standard",
            "online": False,
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "latency_p50_ms": 8000,
            "max_context_tokens": 128_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "analysis", "generation", "coding"],
            "api_base": "http://localhost:11434",
            "model_id": "ollama_chat/Gemma4:26b",
            "extra_body": {"think": False},
            "request_timeout": 600,
        },
        # Back-compat alias — older configs/env still reference the 31B name.
        # Points at the same Gemma4 tag the user actually has pulled locally
        # so existing ROUTER_MODEL=gemma-4-31b-it-ollama deployments keep
        # working without a code change. Drop after all overlays are migrated.
        "gemma-4-31b-it-ollama": {
            "backend": "litellm",
            "tier": "standard",
            "online": False,
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "latency_p50_ms": 8000,
            "max_context_tokens": 128_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "analysis", "generation", "coding"],
            "api_base": "http://localhost:11434",
            "model_id": "ollama_chat/Gemma4:26b",
        },
        # Cross-host benchmark cell — same Gemma4:26b model served by a
        # *different* Ollama instance (192.168.43.10). Pinned so OLLAMA_API_BASE
        # env doesn't redirect it. Used to measure host/network/embedding-stack
        # variance independent of model weights.
        #
        # think:False is mandatory — Gemma4's reasoning mode emits CoT into
        # message.thinking and leaves message.content empty until num_predict
        # is exhausted, which manifests as ~240s timeouts in full-mode agent
        # loops (the router fix in ed97623 covers classify_intent only; the
        # NL2SQL agent path needs its own pin). request_timeout=600s gives
        # us headroom for slow first-token latency on cold loads.
        "gemma4-26b-host43": {
            "backend": "litellm",
            "tier": "standard",
            "online": False,
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "latency_p50_ms": 8000,
            "max_context_tokens": 128_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "analysis", "generation", "coding"],
            "api_base": "http://192.168.43.10:11434",
            "api_base_pinned": True,
            "model_id": "ollama_chat/Gemma4:26b",
            "extra_body": {"think": False},
            "request_timeout": 600,
        },
        # Current LAN Ollama cell used for Gemma4 NL2Semantic2SQL tests.
        # Pinned to 192.168.43.9 so OLLAMA_API_BASE cannot redirect the CQ
        # benchmark/agent path to a different host. Keep thinking disabled for
        # the same reason as host43: the production @NL2SQL path must return
        # concise SQL/tool output instead of model-side reasoning traces.
        "gemma4-26b-host9": {
            "backend": "litellm",
            "tier": "standard",
            "online": False,
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "latency_p50_ms": 8000,
            "max_context_tokens": 128_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "analysis", "generation", "coding"],
            "api_base": "http://192.168.43.9:11434",
            "api_base_pinned": True,
            "model_id": "ollama_chat/Gemma4:26b",
            "extra_body": {"think": False},
            "request_timeout": 600,
        },
        # Gemma4 hackathon demo cell: 26B model on host228.
        # Pinned so the pure-Docker demo keeps using the requested LAN Ollama
        # endpoint even when OLLAMA_API_BASE is changed for another service.
        "gemma4-26b-host228": {
            "backend": "litellm",
            "tier": "standard",
            "online": False,
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "latency_p50_ms": 8000,
            "max_context_tokens": 128_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "analysis", "generation", "coding"],
            "api_base": "http://192.168.25.228:11434",
            "api_base_pinned": True,
            "model_id": "ollama_chat/Gemma4:26b",
            "extra_body": {"think": False},
            "request_timeout": 600,
        },
        # Gemma4 hackathon Windows demo cell: 31B Dense model on host228.
        # Pinned so the local demo and CQ benchmark use the requested LAN
        # Ollama endpoint even when OLLAMA_API_BASE is set for another service.
        "gemma4-31b-host228": {
            "backend": "litellm",
            "tier": "standard",
            "online": False,
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "latency_p50_ms": 12000,
            "max_context_tokens": 128_000,
            "capabilities": ["classification", "extraction", "summarization",
                             "reasoning", "analysis", "generation", "coding"],
            "api_base": "http://192.168.25.228:11434",
            "api_base_pinned": True,
            "model_id": "ollama_chat/Gemma4:31b",
            "extra_body": {"think": False},
            "request_timeout": 900,
        },
    }

    # Mutable registry: starts with builtins, can be extended at runtime
    models: dict[str, dict] = {}

    @classmethod
    def _ensure_initialized(cls):
        if not cls.models:
            cls.models = dict(cls._builtin_models)
            # Allow OLLAMA_API_BASE env to override the hardcoded api_base on
            # any builtin Ollama-backed model. K8s deployments set this to
            # http://ollama:11434 (ExternalName Service pointing at the host).
            # Entries that pin their host explicitly via `api_base_pinned: True`
            # are exempt — used for benchmark cells that need a specific host
            # so the comparison is repeatable regardless of env state.
            ollama_base_env = os.environ.get("OLLAMA_API_BASE")
            if ollama_base_env:
                for name, cfg in cls.models.items():
                    model_id = cfg.get("model_id", "")
                    if model_id.startswith(("ollama/", "ollama_chat/")) \
                            and not cfg.get("api_base_pinned"):
                        cfg["api_base"] = ollama_base_env
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
            backend: "gemini", "deepseek", "litellm", or "lm_studio".
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


def _normalize_openai_compatible_model_name(model_name: str) -> str:
    """Force OpenAI-compatible model IDs through LiteLLM's OpenAI provider."""
    return model_name if model_name.startswith("openai/") else f"openai/{model_name}"


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
    elif backend == "deepseek":
        return _create_deepseek_model(model_name, info)
    elif backend == "qwen":
        return _create_qwen_model(model_name, info)
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
    if model_name.startswith("deepseek"):
        return "deepseek"
    if model_name.startswith("qwen"):
        return "qwen"
    if "/" in model_name:
        # e.g. "openai/gpt-4o", "anthropic/claude-3", "ollama/llama3"
        return "litellm"
    # Default to Gemini for backward compatibility
    default = os.environ.get("MODEL_BACKEND", "gemini")
    return default


def family_of(model_obj) -> str:
    """Return the LLM family name for an ADK model instance.

    Used by NL2SQL evaluation to pick the correct prompt namespace and tool-
    call adapter. The single source of truth for "which family is this LLM?".

    Returns one of:
      - "gemini"    : Google Gemini (gemini-2.5-flash, gemini-2.0-flash, etc.)
      - "gemma"     : Google Gemma (gemma-4-31b-it, etc.) — ALSO uses ADK's
                      Gemini wrapper class but is a distinct family with its
                      own prompt-shape preferences. Detected by model-string
                      substring BEFORE the class-name fallback.
      - "deepseek"  : LiteLlm wrapping a deepseek-v* model
      - "qwen"      : LiteLlm wrapping a Qwen / dashscope model
      - "lm_studio" : LiteLlm pointing at LM Studio's local OpenAI endpoint
      - "litellm"   : LiteLlm with no recognised family signature
      - "unknown"   : anything else
    """
    cls = type(model_obj).__name__
    model_str = (getattr(model_obj, "model", "") or "").lower()
    # Gemma comes BEFORE Gemini class check because Gemma also uses
    # google.adk.models.google_llm.Gemini as its wrapper.
    if "gemma" in model_str:
        return "gemma"
    if cls == "Gemini":
        return "gemini"
    if cls == "LiteLlm":
        if "deepseek" in model_str:
            return "deepseek"
        if "qwen" in model_str or "dashscope" in model_str:
            return "qwen"
        # LM Studio detection: model is "openai/<name>" but base URL points at
        # a local LM Studio endpoint (default http://localhost:1234/v1)
        api_base = os.environ.get("OPENAI_API_BASE", "")
        if "localhost" in api_base or "127.0.0.1" in api_base or "1234" in api_base:
            return "lm_studio"
        return "litellm"
    return "unknown"


def _create_gemini_model(model_name: str):
    """Create a Gemini-class model with retry configuration.

    This is also the entry point for Gemma models, which use the same ADK
    Gemini wrapper class. However, Gemma is only served through Google AI
    Studio, NOT Vertex AI — so when the model_name looks like a Gemma model
    and the process is currently configured for Vertex AI, we temporarily
    disable the Vertex routing by unsetting GOOGLE_GENAI_USE_VERTEXAI in
    this process (and related project env vars). True Gemini models continue
    to use whichever path the parent environment sets.

    Gemini 3.x family supports thinking_level (minimal|low|medium|high). When
    env GEMINI_THINKING_LEVEL is set and model_name matches gemini-3*, we
    return a subclass that injects thinking_config into every LlmRequest. For
    2.5 family we keep the old thinking_budget path (set via THINKING_BUDGET
    if needed; current code does not use this).
    """
    from google.adk.models.google_llm import Gemini
    from google.genai import types

    if "gemma" in model_name.lower():
        # Gemma lives on AI Studio; Vertex AI's publisher catalog does NOT
        # list it (tested 2026-05-10: 404 NOT_FOUND on Vertex, 200 OK on
        # AI Studio with the same model string). Force AI Studio routing
        # for this process.
        if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() == "TRUE":
            os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"
            os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
            os.environ.pop("GOOGLE_CLOUD_LOCATION", None)
            logger.info(
                "Gemma model requested (%s); disabling Vertex AI routing "
                "for this process and falling back to AI Studio endpoint.",
                model_name,
            )

    thinking_level = os.environ.get("GEMINI_THINKING_LEVEL", "").strip().lower()
    if thinking_level and thinking_level in ("minimal", "low", "medium", "high") \
            and model_name.startswith("gemini-3"):
        return _GeminiWithThinkingLevel(
            model=model_name,
            thinking_level=thinking_level,
            retry_options=types.HttpRetryOptions(
                initial_delay=2.0,
                attempts=3,
            ),
        )

    return Gemini(
        model=model_name,
        retry_options=types.HttpRetryOptions(
            initial_delay=2.0,
            attempts=3,
        ),
    )


class _GeminiWithThinkingLevel:
    """Lazy-bound subclass of ADK Gemini that injects thinking_config.

    Defined lazily (not at module import) because the parent class lives in
    google.adk.models.google_llm.Gemini which imports the full ADK runtime.
    Constructing on first instantiation keeps cold import cheap.
    """
    def __new__(cls, *, model: str, thinking_level: str, retry_options):
        from typing import Optional
        from google.adk.models.google_llm import Gemini
        from google.genai import types

        class GeminiWithThinkingLevel(Gemini):
            """Gemini wrapper that sets thinking_config.thinking_level on every request."""
            thinking_level_value: Optional[str] = None

            async def _preprocess_request(self, llm_request):
                await super()._preprocess_request(llm_request)
                if not self.thinking_level_value or not llm_request.config:
                    return
                existing = getattr(llm_request.config, "thinking_config", None)
                include = getattr(existing, "include_thoughts", None) if existing else None
                llm_request.config.thinking_config = types.ThinkingConfig(
                    thinking_level=self.thinking_level_value,
                    include_thoughts=include,
                )

        inst = GeminiWithThinkingLevel(
            model=model,
            retry_options=retry_options,
            thinking_level_value=thinking_level,
        )
        logger.info(
            "Gemini model %s wrapped with thinking_level=%s",
            model, thinking_level,
        )
        return inst


def _create_lm_studio_model(model_name: str, info: dict):
    """Create a LiteLLM model pointing to LM Studio's OpenAI-compatible API."""
    from google.adk.models.lite_llm import LiteLlm

    api_base = info.get("api_base", _get_lm_studio_base_url())

    # LiteLLM uses "openai/" prefix for OpenAI-compatible endpoints
    litellm_name = _normalize_openai_compatible_model_name(model_name)

    # Set env vars that litellm needs
    os.environ.setdefault("OPENAI_API_KEY", "lm-studio")
    os.environ["OPENAI_API_BASE"] = api_base

    return LiteLlm(model=litellm_name)


def _create_deepseek_model(model_name: str, info: dict):
    """Create a DeepSeek model via the OpenAI-compatible LiteLLM path."""
    from google.adk.models.lite_llm import LiteLlm

    api_base = info.get("api_base", "https://api.deepseek.com")
    effective_name = info.get("model_id", f"openai/{model_name}")
    api_key_env = info.get("api_key_env", "DEEPSEEK_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        os.environ.pop("OPENAI_API_KEY", None)
        raise RuntimeError(f"{api_key_env} not set")

    os.environ["OPENAI_API_BASE"] = api_base
    os.environ["OPENAI_API_KEY"] = api_key

    # Same NO_PROXY defensive step as _create_qwen_model.
    _existing_no_proxy = os.environ.get("NO_PROXY", "") or os.environ.get("no_proxy", "")
    _merged = ",".join(_h for _h in (
        _existing_no_proxy.split(",") + ["api.deepseek.com"]
    ) if _h)
    os.environ["NO_PROXY"] = _merged
    os.environ["no_proxy"] = _merged

    # deepseek-v4-flash defaults to thinking.type=enabled with reasoning_effort
    # auto-upgraded to "max" in agent scenarios. That blows wall-clock and token
    # budget on tool-calling loops (every turn must echo reasoning_content per
    # DeepSeek API contract). For agent/tool-calling use we disable thinking;
    # callers needing CoT can pass thinking_enabled=True via info.
    thinking_enabled = info.get("thinking_enabled", False)
    extra_body = {
        "thinking": {"type": "enabled" if thinking_enabled else "disabled"}
    }
    return LiteLlm(model=effective_name, extra_body=extra_body)


def _create_qwen_model(model_name: str, info: dict):
    """Create a Qwen model via Aliyun token-plan MaaS OpenAI-compatible path.

    Qwen3 family is served through Aliyun's MaaS `compatible-mode` v1 endpoint
    which speaks the OpenAI Chat Completions spec, so LiteLLM routes through
    the same `openai/<model>` prefix as DeepSeek. Qwen3 family supports a
    thinking mode; for agent / tool-calling we disable it by default to avoid
    the same wall-clock / token blowup we saw with DeepSeek's
    reasoning_content. Override via `info[\"thinking_enabled\"] = True`.

    Network note: HTTPS_PROXY=127.0.0.1:* does not route the token-plan
    endpoint, so we add it to NO_PROXY for this process. DNS works fine; only
    HTTPS through local proxy fails (proxy doesn't know about MaaS hosts).
    """
    from google.adk.models.lite_llm import LiteLlm

    api_base = info.get(
        "api_base", "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    effective_name = info.get("model_id", f"openai/{model_name}")
    api_key_env = info.get("api_key_env", "DASHSCOPE_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        os.environ.pop("OPENAI_API_KEY", None)
        raise RuntimeError(f"{api_key_env} not set")

    # Ensure local proxy does NOT intercept requests to the MaaS endpoint.
    # The host resolves and pings fine, but the local corporate proxy
    # (HTTPS_PROXY=127.0.0.1:*) hangs on CONNECT — add MaaS hosts to NO_PROXY
    # so the OpenAI client bypasses the proxy for these destinations.
    _bypass_hosts = [
        "token-plan.cn-beijing.maas.aliyuncs.com",
        "dashscope.aliyuncs.com",
    ]
    _existing_no_proxy = os.environ.get("NO_PROXY", "") or os.environ.get("no_proxy", "")
    _merged = ",".join(_h for _h in (_existing_no_proxy.split(",") + _bypass_hosts) if _h)
    os.environ["NO_PROXY"] = _merged
    os.environ["no_proxy"] = _merged

    os.environ["OPENAI_API_BASE"] = api_base
    os.environ["OPENAI_API_KEY"] = api_key

    # Qwen thinking-mode passthrough — dashscope expects `enable_thinking`
    # in extra_body (different field name from DeepSeek's `thinking`). We
    # default to disabled so agent loops stay tight; callers needing CoT
    # can override via info["thinking_enabled"].
    thinking_enabled = info.get("thinking_enabled", False)
    extra_body = {"enable_thinking": bool(thinking_enabled)}
    return LiteLlm(model=effective_name, extra_body=extra_body)


def _create_litellm_model(model_name: str, info: dict):
    """Create a generic LiteLLM model.

    v23.0: Supports extra_headers and extra_body for vLLM endpoints
    (e.g. Gemma 4 self-hosted with enable_thinking).
    v6: Supports `ollama_chat/` prefix for Ollama local deployments. Per ADK
    docs (https://adk.wiki/agents/models/ollama/) the `ollama_chat/` provider
    MUST be used instead of `ollama/`; the latter causes infinite tool-call
    loops on most Ollama-served models.
    """
    from google.adk.models.lite_llm import LiteLlm

    # Use model_id override if specified (e.g. "ollama_chat/gemma4:31b")
    effective_name = info.get("model_id", model_name)

    api_base = info.get("api_base")
    if api_base:
        # Provider-specific env var handling
        if effective_name.startswith("openai/"):
            os.environ["OPENAI_API_BASE"] = api_base
        elif effective_name.startswith(("ollama/", "ollama_chat/")):
            os.environ["OLLAMA_API_BASE"] = api_base
            # Add the Ollama host to NO_PROXY so local-network deployments
            # (e.g. 192.168.x.x) bypass the corporate HTTPS_PROXY which
            # would otherwise CONNECT-hang on internal hosts.
            try:
                from urllib.parse import urlparse
                host = urlparse(api_base).hostname
            except Exception:
                host = None
            if host:
                _existing_np = (os.environ.get("NO_PROXY", "")
                                or os.environ.get("no_proxy", ""))
                _merged = ",".join(
                    _h for _h in (_existing_np.split(",") + [host]) if _h
                )
                os.environ["NO_PROXY"] = _merged
                os.environ["no_proxy"] = _merged

    # Set API key from env var name if specified
    api_key_env = info.get("api_key_env")
    if api_key_env:
        api_key = os.environ.get(api_key_env, "")
        if api_key and effective_name.startswith("openai/"):
            os.environ["OPENAI_API_KEY"] = api_key

    # Optional per-entry request timeout (seconds). Useful for slow Ollama
    # hosts where the default 600s litellm timeout still trips on long
    # full-mode prompts. Pass it through to litellm.completion via the
    # LiteLlm wrapper's kwargs.
    extra_kwargs: dict = {}
    request_timeout = info.get("request_timeout")
    if request_timeout is not None:
        extra_kwargs["timeout"] = request_timeout

    # Forward extra_body if the registry entry pinned one (e.g. for Ollama
    # reasoning models we may want to disable thinking mode).
    if info.get("extra_body"):
        extra_kwargs["extra_body"] = info["extra_body"]

    return LiteLlm(model=effective_name, **extra_kwargs)


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
