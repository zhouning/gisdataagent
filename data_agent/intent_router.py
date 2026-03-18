"""
Intent Router — Semantic classification of user queries into pipeline categories.

Extracted from app.py (S-1 refactoring). Uses Gemini 2.0 Flash for low-latency
intent classification with multimodal support (text + images + PDF context).
"""
import logging

from google import genai as genai_client
from google.genai import types

logger = logging.getLogger("data_agent.intent_router")

# Dedicated GenAI client for routing (outside ADK agents)
_router_client = genai_client.Client()


def classify_intent(text: str, previous_pipeline: str = None,
                    image_paths: list = None, pdf_context: str = None) -> tuple:
    """
    Uses Gemini Flash to semantically classify user intent into one of the 3 pipelines,
    plus tool subcategories for dynamic tool filtering (v7.5.6).
    Supports multimodal input: images are embedded directly, PDF text is appended to prompt.
    Returns: (intent, reason, router_tokens, tool_categories) where intent is
    'OPTIMIZATION', 'GOVERNANCE', 'GENERAL', or 'AMBIGUOUS'.
    """
    try:
        prev_hint = ""
        if previous_pipeline:
            prev_hint = f"\n        - The previous turn used the {previous_pipeline.upper()} pipeline. If the user references prior results (上面, 刚才, 继续, 之前, 在此基础上), prefer routing to the SAME pipeline: {previous_pipeline.upper()}."

        # Append PDF context summary if available
        pdf_hint = ""
        if pdf_context:
            truncated = pdf_context[:2000]
            pdf_hint = f"\n\n        [Attached PDF content summary]:\n        {truncated}"

        prompt = f"""
        You are the Intent Router for a GIS Data Agent. Classify the User Input into ONE of these categories:

        1. **GOVERNANCE**: Data auditing, quality check, topology fix, standardization, consistency check. (Keywords: 治理, 审计, 质检, 核查, 拓扑, 标准)
        2. **OPTIMIZATION**: Land use optimization, DRL, FFI calculation, spatial layout planning. (Keywords: 优化, 布局, 破碎化, 规划)
        3. **GENERAL**: General queries, SQL, visualization, mapping, simple analysis, clustering, heatmap, buffer, site selection, memories, preferences. (Keywords: 查询, 地图, 热力图, 聚类, 选址, 分析, 筛选, 数据库, 记忆, 偏好, 记住, 历史)
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

        User Input: "{text}"{pdf_hint}

        Rules:
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
                http_options=types.HttpOptions(timeout=30_000),  # 30s
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
        if "OPTIMIZATION" in intent: return ("OPTIMIZATION", reason, router_tokens, tool_cats)
        if "GOVERNANCE" in intent: return ("GOVERNANCE", reason, router_tokens, tool_cats)
        if "AMBIGUOUS" in intent: return ("AMBIGUOUS", reason, router_tokens, tool_cats)
        if "GENERAL" in intent: return ("GENERAL", reason, router_tokens, tool_cats)
        return ("GENERAL", reason, router_tokens, tool_cats)
    except Exception as e:
        logger.error("Router error: %s", e)
        return ("GENERAL", "", 0, set())


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
        )
        return response.text.strip()
    except Exception as e:
        logger.error("Plan generation error: %s", e)
        return ""
