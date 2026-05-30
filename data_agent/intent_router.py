"""
Intent Router — Semantic classification of user queries into pipeline categories.

Extracted from app.py (S-1 refactoring). Uses Gemini 2.0 Flash by default,
but falls back to any LiteLLM-supported model (Ollama / vLLM / OpenAI-
compatible) when ROUTER_MODEL points at a non-Gemini backend. v14.3 adds
multi-language detection (zh/en/ja); v25.x adds local-LLM routing.
"""
import logging
import os
import re

from google import genai as genai_client
from google.genai import types

logger = logging.getLogger("data_agent.intent_router")

# Dedicated GenAI client for routing (outside ADK agents). Initialised lazily
# so a fully-local deployment with no GOOGLE_API_KEY doesn't fail at import
# time -- the router falls through to the LiteLLM path instead.
_router_client = None


def _is_local_router_backend(model_name: str) -> bool:
    """Return True iff the configured router model needs the LiteLLM path
    (Ollama / vLLM / OpenAI-compatible) rather than Google GenAI."""
    if not model_name:
        return False
    if model_name.startswith(("ollama/", "ollama_chat/", "openai/")):
        return True
    # Look up the registered model in ModelRegistry; backend != google_genai
    # also routes through LiteLLM.
    try:
        from data_agent.model_gateway import ModelRegistry
        info = ModelRegistry.get_model_info(model_name)
        backend = (info or {}).get("backend", "")
        if backend in ("litellm", "ollama", "vllm", "lm_studio", "openai"):
            return True
    except Exception:
        pass
    return False


def _ensure_genai_client():
    global _router_client
    if _router_client is None:
        _router_client = genai_client.Client()
    return _router_client


def _route_via_litellm(prompt: str, model_name: str, image_paths=None) -> tuple[str, int, int]:
    """Run a single completion through LiteLLM. Returns (text, in_tokens, out_tokens).

    Images are dropped on the LiteLLM path: most local Ollama-served models
    (gemma2/3/4) don't support vision, and the router prompt's text-only
    rules are sufficient for classification. Multimodal routing stays on the
    Gemini path.

    Reasoning models (Gemma 4, Qwen3, DeepSeek-R1) default to emitting their
    chain-of-thought into the `thinking` field, leaving `content` empty until
    the `num_predict` budget runs out — which can blow past 200 tokens before
    a single classification token is emitted. The router prompt expects a
    one-liner ("CATEGORY|REASON|TOOLS:..."), so we explicitly disable the
    thinking pathway via Ollama's `think: false` option. Verified against
    gemma4:31b on 2026-05-30: 38 tokens, ~25 tok/s, correct OPTIMIZATION
    classification on Chinese input. Without `think: false` the same prompt
    produced an empty content string with 300 tokens trapped in `thinking`.
    """
    if image_paths:
        logger.debug("[Router] LiteLLM backend doesn't accept images; ignoring %d image(s)",
                     len(image_paths))
    import litellm
    # Resolve the LiteLLM-side model id and base URL from the registry.
    api_base = None
    effective_id = model_name
    try:
        from data_agent.model_gateway import ModelRegistry
        info = ModelRegistry.get_model_info(model_name) or {}
        effective_id = info.get("model_id", model_name)
        api_base = info.get("api_base") or os.environ.get("OLLAMA_API_BASE")
    except Exception:
        api_base = os.environ.get("OLLAMA_API_BASE")

    kwargs = {
        "model": effective_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 256,
        "timeout": 30,
    }
    if api_base:
        kwargs["api_base"] = api_base
    # Disable reasoning-mode thinking for Ollama-served models. Other LiteLLM
    # backends (OpenAI, vLLM-without-thinking) silently ignore the param.
    if effective_id.startswith(("ollama/", "ollama_chat/")):
        kwargs["extra_body"] = {"think": False}

    resp = litellm.completion(**kwargs)
    text_out = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
    out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
    return text_out.strip(), in_tok, out_tok


# ---------------------------------------------------------------------------
# Language Detection (v14.3)
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """Detect input language from character distribution.

    Returns: 'zh' (Chinese), 'en' (English), 'ja' (Japanese), or 'zh' as default.
    """
    if not text:
        return "zh"
    # Count character types
    cjk = 0
    hiragana_katakana = 0
    latin = 0
    for ch in text:
        cp = ord(ch)
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            cjk += 1
        elif 0x3040 <= cp <= 0x30FF:
            hiragana_katakana += 1
        elif 0x0041 <= cp <= 0x007A:
            latin += 1

    total = cjk + hiragana_katakana + latin
    if total == 0:
        return "zh"
    if hiragana_katakana / max(total, 1) > 0.1:
        return "ja"
    if latin / max(total, 1) > 0.7:
        return "en"
    return "zh"


_LANG_HINTS = {
    "zh": "请用中文回复。",
    "en": "Please respond in English.",
    "ja": "日本語で回答してください。",
}


# ---------------------------------------------------------------------------
# Capability-query shortcut — route meta-questions directly to GENERAL
# ---------------------------------------------------------------------------
# These patterns catch "what can you do?" style questions so they skip the
# Gemini router and never land in AMBIGUOUS. The agent's query_capabilities
# tool (CapabilityQAToolset) handles the actual explanation.
_CAPABILITY_QUERY_PATTERNS = [
    r"你\s*(能|可以|会|支持)\s*(做|干|处理|分析|提供)?\s*(什么|啥|哪些)",
    r"(有|能|可以|支持)\s*(什么|啥|哪些)\s*(功能|能力|工具|用途)",
    r"(能不能|可不可以|能否|是否|会不会).{0,20}(做|处理|分析|支持|完成)",
    r"你\s*(是|做)\s*什么\s*的",
    r"你\s*是\s*(做|干)?\s*什么\s*的",
    r"介绍\s*一?下?\s*(你|你的)?\s*(功能|能力|用途)",
    r"(能力|功能)\s*清单",
    r"帮助\s*文档",
    r"\bwhat\s+can\s+you\s+do\b",
    r"\bwhat\s+are\s+your\s+(capabilities|features|functions)\b",
    r"\b(list|show)\s+(all\s+)?(capabilities|features|functions|tools)\b",
    r"\bhelp\b\s*$",
    r"\bcan\s+you\s+.{0,40}\?",
]

_CAPABILITY_QUERY_REGEX = re.compile(
    "|".join(_CAPABILITY_QUERY_PATTERNS), re.IGNORECASE
)


def _is_capability_query(text: str) -> bool:
    """Detect whether the user is asking about system capabilities."""
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_CAPABILITY_QUERY_REGEX.search(stripped))


def _get_router_model() -> str:
    """Get the configured router model name (v23.0)."""
    try:
        from data_agent.model_config import get_config_manager
        return get_config_manager().get_router_model()
    except Exception:
        return os.environ.get("ROUTER_MODEL", "gemini-2.0-flash")


def classify_intent(text: str, previous_pipeline: str = None,
                    image_paths: list = None, pdf_context: str = None) -> tuple:
    """
    Uses Gemini Flash to semantically classify user intent into one of the pipelines,
    plus tool subcategories for dynamic tool filtering (v7.5.6).
    Supports multimodal input: images are embedded directly, PDF text is appended to prompt.
    Returns: (intent, reason, router_tokens, tool_categories, language) where intent is
    'OPTIMIZATION', 'GOVERNANCE', 'GENERAL', 'WORKFLOW', or 'AMBIGUOUS',
    and language is 'zh'/'en'/'ja'.
    """
    lang = detect_language(text)
    import time as _time
    _router_start = _time.perf_counter()
    # Shortcut: meta-questions about the system itself route directly to GENERAL
    # so the agent can call query_capabilities (always in CORE_TOOLS) instead of
    # being misclassified as AMBIGUOUS.
    if text and _is_capability_query(text) and not image_paths:
        try:
            from data_agent.observability import record_intent
            record_intent("GENERAL", lang, _time.perf_counter() - _router_start)
        except Exception:
            pass
        return ("GENERAL", "capability_query_shortcut", 0, set(), lang, "agentic")
    try:
        prev_hint = ""
        if previous_pipeline:
            prev_hint = f"\n        - The previous turn used the {previous_pipeline.upper()} pipeline. If the user is continuing the conversation (上面, 刚才, 继续, 之前, 在此基础上) or confirming/agreeing (确认, 确认无误, 好的, 是的, 对, 没问题, OK, yes, 可以, 执行, 开始, 同意), ALWAYS route to the SAME pipeline: {previous_pipeline.upper()}. Short confirmations are NOT new tasks."

        # Append PDF context summary if available
        pdf_hint = ""
        if pdf_context:
            truncated = pdf_context[:2000]
            pdf_hint = f"\n\n        [Attached PDF content summary]:\n        {truncated}"

        prompt = f"""
        You are the Intent Router for a GIS Data Agent. Classify the User Input into ONE of these categories:

        1. **GOVERNANCE**: Data auditing, quality check, topology fix, standardization, consistency check. (Keywords: 治理, 审计, 质检, 核查, 拓扑, 标准)
        2. **OPTIMIZATION**: Land use optimization, DRL, FFI calculation, spatial layout planning. (Keywords: 优化, 布局, 破碎化, 规划)
        3. **GENERAL**: General queries, SQL, visualization, mapping, simple analysis, clustering, heatmap, buffer, site selection, memories, preferences, world model prediction. (Keywords: 查询, 地图, 热力图, 聚类, 选址, 分析, 筛选, 数据库, 记忆, 偏好, 记住, 历史, 世界模型, world model, LULC预测, 土地利用预测, 变化预测)
        4. **WORKFLOW**: Execute a predefined multi-step workflow / quality control pipeline. The user explicitly wants to run a named workflow template (e.g. 标准质检, 快速质检, DLG质检, DOM质检, DEM质检, 三维模型质检, 完整质检). (Keywords: 执行质检流程, 运行质检, 执行工作流, 跑一下质检, 启动质检, 标准质检, 快速质检, DLG质检, DOM质检, DEM质检, 三维模型质检)
        5. **AMBIGUOUS**: The input is too vague, unclear, or could match multiple pipelines equally. E.g. greetings, single-word inputs, or no clear GIS task.

        Additionally, identify which tool subcategories are needed (comma-separated, minimum list):
        - spatial_processing: buffer, clip, overlay, tessellation, clustering, zonal stats, geocoding, spatial join
        - poi_location: POI search, population, driving distance, admin boundaries
        - remote_sensing: raster/NDVI/DEM/LULC/watershed/hydrology/流域/水文/河网/汇水
        - database_management: PostGIS import/export/describe table schema
        - quality_audit: topology check, field standards, semantic layer, consistency
        - streaming_iot: real-time/IoT data streams, geofence
        - collaboration: team management, templates, asset management
        - advanced_analysis: spatial statistics (Moran/hotspot), data fusion, knowledge graph
        - world_model: world model prediction, LULC forecasting, scenario simulation, 世界模型, 土地利用预测, 干预预测, 反事实对比
        - causal_reasoning: causal DAG, counterfactual reasoning, causal mechanism, what-if scenarios, 因果推理, 因果图, 反事实

        User Input: "{text}"{pdf_hint}

        Rules:
        - CRITICAL: Short confirmations (确认, 确认无误, 好的, 是的, 对, OK, yes, 可以, 执行, 开始) are NOT new tasks. They continue the previous conversation. If a previous pipeline exists, route to the SAME pipeline. Otherwise, treat as AMBIGUOUS.
        - If the user explicitly asks to "execute/run a QC workflow" (执行质检, 运行质检流程, 跑质检, 启动质检, 标准质检, 快速质检, DLG质检, DOM质检, DEM质检, 三维模型质检, 完整质检, 执行工作流), choose WORKFLOW. Note: WORKFLOW is different from GOVERNANCE — GOVERNANCE is ad-hoc analysis, WORKFLOW is running a predefined multi-step template.
        - If input mentions "世界模型" or "world model" or "LULC预测" or "土地利用预测", prioritize GENERAL (the world model tool is in the General pipeline).
        - If input mentions "optimize" or "FFI", prioritize OPTIMIZATION.
        - If input is asking "what data is there" or "show map", choose GENERAL.{prev_hint}
        - If the input is a greeting (你好, hello, hi), casual chat, or contains no identifiable GIS task, output AMBIGUOUS.
        - If the input could reasonably belong to two pipelines equally, output AMBIGUOUS.
        - If images are attached, consider their visual content as additional context for classification.
        - Output format: CATEGORY|REASON|TOOLS:cat1,cat2
        - Examples: "GENERAL|用户请求缓冲区分析|TOOLS:spatial_processing" or "GOVERNANCE|数据质检|TOOLS:quality_audit"
        - If unsure which tools are needed or for AMBIGUOUS inputs: "CATEGORY|REASON|TOOLS:all"
        """

        # Build multimodal content for Gemini: text + optional images
        content_parts = [prompt]
        if image_paths:
            try:
                from PIL import Image as PILImage
                for img_path in image_paths[:3]:  # limit to 3 images for router
                    img = PILImage.open(img_path)
                    if img.mode in ("RGBA", "P", "LA"):
                        img = img.convert("RGB")
                    # Resize for router (smaller than pipeline images)
                    w, h = img.size
                    if max(w, h) > 512:
                        ratio = 512 / max(w, h)
                        img = img.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)
                    content_parts.append(img)
            except Exception as img_err:
                logger.debug("Could not load images for router: %s", img_err)

        try:
            router_model_name = _get_router_model()
            response = None
            if _is_local_router_backend(router_model_name):
                # Pure local backend (Ollama/vLLM/OpenAI-compatible). Skip the
                # Gemini Client and don't fall back to DeepSeek either — when
                # the operator opts into local LLM, network round-trips to
                # external providers are explicitly off the table.
                _text_prompt = content_parts[0] if isinstance(content_parts[0], str) else str(content_parts[0])
                raw, _in_tok, _out_tok = _route_via_litellm(
                    _text_prompt, router_model_name, image_paths=image_paths,
                )
                router_input_tokens = _in_tok
                router_output_tokens = _out_tok
            else:
                response = _ensure_genai_client().models.generate_content(
                    model=router_model_name,
                    contents=content_parts,
                    config=types.GenerateContentConfig(
                        http_options=types.HttpOptions(
                            timeout=30_000,  # 30s
                            retry_options=types.HttpRetryOptions(
                                initial_delay=2.0,
                                attempts=3,
                            ),
                        ),
                    ),
                )
                raw = response.text.strip()
                router_input_tokens = 0
                router_output_tokens = 0
        except Exception as _gemini_err:
            _err_str = str(_gemini_err)
            if "429" not in _err_str and "RESOURCE_EXHAUSTED" not in _err_str:
                raise
            logger.info("[Router] Gemini 429, falling back to DeepSeek")
            try:
                from .llm_client import generate_text
                _text_prompt = content_parts[0] if isinstance(content_parts[0], str) else str(content_parts[0])
                raw = generate_text(_text_prompt, tier="fast", timeout_ms=20_000)
                router_input_tokens = 0
                router_output_tokens = 0
            except Exception as _ds_err:
                logger.error("[Router] DeepSeek fallback failed: %s", _ds_err)
                raise _gemini_err
        # Track router token consumption — only update from response.usage when
        # we used the Gemini path (LiteLLM populates the counts above).
        try:
            if response and hasattr(response, 'usage_metadata') and response.usage_metadata:
                router_input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
                router_output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
        except NameError:
            pass  # DeepSeek fallback path — no response object
        router_tokens = router_input_tokens + router_output_tokens

        # --- Parse tool categories (v7.5.6) ---
        tool_cats = set()
        if "TOOLS:" in raw:
            tools_part = raw.split("TOOLS:", 1)[1].strip()
            if tools_part and tools_part.lower() != "all":
                tool_cats = {c.strip() for c in tools_part.split(",") if c.strip()}
            # Strip unknown categories — only keep those defined in TOOL_CATEGORIES
            from data_agent.tool_filter import VALID_CATEGORIES
            unknown = tool_cats - VALID_CATEGORIES
            if unknown:
                logger.debug("Router returned unknown tool categories: %s (stripped)", unknown)
                tool_cats = tool_cats & VALID_CATEGORIES
            # Remove TOOLS: suffix from the raw text for intent/reason parsing
            raw = raw.split("|TOOLS:", 1)[0] if "|TOOLS:" in raw else raw.split("TOOLS:", 1)[0]
            raw = raw.strip()

        if "|" in raw:
            parts = raw.split("|", 1)
            intent = parts[0].strip().upper()
            reason = parts[1].strip()
        else:
            intent = raw.upper()
            reason = ""
        if "OPTIMIZATION" in intent: result_intent = "OPTIMIZATION"
        elif "GOVERNANCE" in intent: result_intent = "GOVERNANCE"
        elif "WORKFLOW" in intent: result_intent = "WORKFLOW"
        elif "AMBIGUOUS" in intent: result_intent = "AMBIGUOUS"
        elif "GENERAL" in intent: result_intent = "GENERAL"
        else: result_intent = "GENERAL"

        # Record intent metrics (v14.5)
        try:
            from data_agent.observability import record_intent
            record_intent(result_intent, lang, _time.perf_counter() - _router_start)
        except Exception:
            pass

        # Detect execution mode (v20.0): agentic (default) vs workflow
        execution_mode = _detect_execution_mode(text, result_intent)

        return (result_intent, reason, router_tokens, tool_cats, lang, execution_mode)
    except Exception as e:
        logger.error("Router error: %s", e)
        try:
            from data_agent.observability import record_intent
            record_intent("GENERAL", lang, _time.perf_counter() - _router_start)
        except Exception:
            pass
        return ("GENERAL", "", 0, set(), detect_language(text), "agentic")


# ---------------------------------------------------------------------------
# Execution mode detection (v20.0)
# ---------------------------------------------------------------------------

_WORKFLOW_KEYWORDS = {
    "zh": ["执行工作流", "按模板运行", "运行模板", "工作流执行", "按流程", "批量处理", "按步骤执行"],
    "en": ["run workflow", "execute workflow", "run template", "batch process", "follow template"],
}


def _detect_execution_mode(text: str, intent: str) -> str:
    """Detect whether user wants agentic (ad-hoc) or workflow (deterministic) mode.

    Returns 'workflow' if explicit workflow keywords detected or WORKFLOW intent,
    otherwise 'agentic'.
    """
    if intent == "WORKFLOW":
        return "workflow"
    text_lower = text.lower()
    for keywords in _WORKFLOW_KEYWORDS.values():
        for kw in keywords:
            if kw in text_lower:
                return "workflow"
    return "agentic"


def should_decompose(text: str) -> bool:
    """Heuristic: returns True when user text likely contains multiple analysis steps."""
    if len(text) < 15:
        return False
    # Chinese multi-step markers
    zh_markers = ["然后", "接着", "之后", "并且", "同时", "首先", "第一步", "第二步",
                  "最后", "再", "还要", "以及", "分别"]
    # English multi-step markers
    en_markers = ["then", "after that", "next", "and also", "first", "second",
                  "finally", "additionally", "followed by", "step 1", "step 2"]
    text_lower = text.lower()
    marker_count = sum(1 for m in zh_markers + en_markers if m in text_lower)
    # Need at least 2 markers or a numbered list pattern
    if marker_count >= 2:
        return True
    # Numbered list pattern: "1. xxx 2. xxx" or "1、xxx 2、xxx"
    numbered = re.findall(r'(?:^|[\s\n])[1-9][.、)]\s*\S', text, re.MULTILINE)
    if len(numbered) >= 2:
        return True
    return False


def generate_analysis_plan(user_text: str, intent: str, uploaded_files: list) -> str:
    """Generate a lightweight analysis plan for user confirmation before expensive pipelines."""
    try:
        from data_agent.prompts import get_prompt

        files_info = "\n".join(f"- {f}" for f in uploaded_files) if uploaded_files else "无上传文件"
        prompt_template = get_prompt("planner", "plan_generation_prompt")
        prompt = prompt_template.format(intent=intent, user_text=user_text, files_info=files_info)

        router_model_name = _get_router_model()
        if _is_local_router_backend(router_model_name):
            text, _, _ = _route_via_litellm(prompt, router_model_name)
            return text

        response = _ensure_genai_client().models.generate_content(
            model=router_model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(
                        initial_delay=2.0,
                        attempts=3,
                    ),
                ),
            ),
        )
        return response.text.strip()
    except Exception as e:
        logger.error("Plan generation error: %s", e)
        return ""
