"""
Intent Router — Semantic classification of user queries into pipeline categories.

Extracted from app.py (S-1 refactoring). Uses Gemini 2.0 Flash for low-latency
intent classification with multimodal support (text + images + PDF context).
v14.3: Added multi-language detection (zh/en/ja).
"""
import logging
import re

from google import genai as genai_client
from google.genai import types

logger = logging.getLogger("data_agent.intent_router")

# Dedicated GenAI client for routing (outside ADK agents)
_router_client = genai_client.Client()


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


def classify_intent(text: str, previous_pipeline: str = None,
                    image_paths: list = None, pdf_context: str = None) -> tuple:
    """
    Uses Gemini Flash to semantically classify user intent into one of the 3 pipelines,
    plus tool subcategories for dynamic tool filtering (v7.5.6).
    Supports multimodal input: images are embedded directly, PDF text is appended to prompt.
    Returns: (intent, reason, router_tokens, tool_categories, language) where intent is
    'OPTIMIZATION', 'GOVERNANCE', 'GENERAL', or 'AMBIGUOUS', and language is 'zh'/'en'/'ja'.
    """
    lang = detect_language(text)
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
        4. **AMBIGUOUS**: The input is too vague, unclear, or could match multiple pipelines equally. E.g. greetings, single-word inputs, or no clear GIS task.

        Additionally, identify which tool subcategories are needed (comma-separated, minimum list):
        - spatial_processing: buffer, clip, overlay, tessellation, clustering, zonal stats, geocoding, spatial join
        - poi_location: POI search, population, driving distance, admin boundaries
        - remote_sensing: raster/NDVI/DEM/LULC/watershed/hydrology/流域/水文/河网/汇水
        - database_management: PostGIS import/export/describe table schema
        - quality_audit: topology check, field standards, semantic layer, consistency
        - streaming_iot: real-time/IoT data streams, geofence
        - collaboration: team management, templates, asset management
        - advanced_analysis: spatial statistics (Moran/hotspot), data fusion, knowledge graph
        - world_model: world model prediction, LULC forecasting, scenario simulation, 世界模型, 土地利用预测

        User Input: "{text}"{pdf_hint}

        Rules:
        - CRITICAL: Short confirmations (确认, 确认无误, 好的, 是的, 对, OK, yes, 可以, 执行, 开始) are NOT new tasks. They continue the previous conversation. If a previous pipeline exists, route to the SAME pipeline. Otherwise, treat as AMBIGUOUS.
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

        response = _router_client.models.generate_content(
            model='gemini-2.0-flash',
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
        # Track router token consumption
        router_input_tokens = 0
        router_output_tokens = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            router_input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            router_output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
        router_tokens = router_input_tokens + router_output_tokens

        raw = response.text.strip()

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
        elif "AMBIGUOUS" in intent: result_intent = "AMBIGUOUS"
        elif "GENERAL" in intent: result_intent = "GENERAL"
        else: result_intent = "GENERAL"

        # Record intent metrics (v14.5)
        try:
            from data_agent.observability import record_intent
            import time as _time
            record_intent(result_intent, lang, 0)  # duration tracked at caller level
        except Exception:
            pass

        return (result_intent, reason, router_tokens, tool_cats, lang)
    except Exception as e:
        logger.error("Router error: %s", e)
        return ("GENERAL", "", 0, set(), detect_language(text))


def generate_analysis_plan(user_text: str, intent: str, uploaded_files: list) -> str:
    """Generate a lightweight analysis plan for user confirmation before expensive pipelines."""
    try:
        from data_agent.prompts import get_prompt

        files_info = "\n".join(f"- {f}" for f in uploaded_files) if uploaded_files else "无上传文件"
        prompt_template = get_prompt("planner", "plan_generation_prompt")
        prompt = prompt_template.format(intent=intent, user_text=user_text, files_info=files_info)

        response = _router_client.models.generate_content(
            model='gemini-2.0-flash',
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
