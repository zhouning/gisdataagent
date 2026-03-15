"""
Agent Composer — dynamic agent specialization & composition (v12.0.2, Ch21).

Analyzes data profiles and dynamically assembles specialized LlmAgent instances
with domain-appropriate toolsets and instructions, instead of fixed pipelines.

All operations are non-fatal.
"""
import os
from dataclasses import dataclass, field
from typing import Optional

try:
    from .observability import get_logger
    logger = get_logger("agent_composer")
except Exception:
    import logging
    logger = logging.getLogger("agent_composer")


DYNAMIC_COMPOSITION = os.environ.get("DYNAMIC_COMPOSITION", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Data Profile
# ---------------------------------------------------------------------------

@dataclass
class DataProfile:
    """Extracted characteristics of a spatial dataset."""
    file_path: str = ""
    file_name: str = ""
    extension: str = ""
    row_count: int = 0
    column_count: int = 0
    columns: list[str] = field(default_factory=list)
    geometry_types: list[str] = field(default_factory=list)
    crs: str = ""
    has_coordinates: bool = False
    numeric_columns: list[str] = field(default_factory=list)
    domain: str = "general"  # landuse, transport, hydrology, ecology, urban, general
    domain_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# Domain detection keywords
_DOMAIN_KEYWORDS = {
    "landuse": ["dlbm", "地类", "用地", "耕地", "林地", "land_use", "landuse", "parcel", "farmland",
                "forest", "旱地", "水田", "建设用地", "草地"],
    "transport": ["road", "道路", "highway", "路网", "交通", "公路", "铁路", "bridge", "dl"],
    "hydrology": ["water", "river", "lake", "流域", "水体", "河流", "湖泊", "watershed", "sx"],
    "ecology": ["ndvi", "vegetation", "生态", "植被", "ecology", "habitat", "biodiversity"],
    "urban": ["building", "poi", "建筑", "城市", "urban", "district", "区划", "行政", "bldg"],
}


def extract_profile(file_path: str) -> DataProfile:
    """Extract a DataProfile from a spatial data file."""
    profile = DataProfile(
        file_path=file_path,
        file_name=os.path.basename(file_path),
        extension=os.path.splitext(file_path)[1].lower(),
    )

    try:
        ext = profile.extension
        if ext in (".shp", ".geojson", ".gpkg", ".kml"):
            import geopandas as gpd
            gdf = gpd.read_file(file_path, rows=100)  # sample first 100 rows
            profile.row_count = len(gdf)
            profile.columns = list(gdf.columns)
            profile.column_count = len(gdf.columns)
            profile.geometry_types = list(gdf.geom_type.unique()) if "geometry" in gdf.columns else []
            profile.crs = str(gdf.crs) if gdf.crs else ""
            profile.numeric_columns = gdf.select_dtypes(include="number").columns.tolist()

        elif ext == ".csv":
            import pandas as pd
            df = pd.read_csv(file_path, nrows=100)
            profile.row_count = len(df)
            profile.columns = list(df.columns)
            profile.column_count = len(df.columns)
            profile.numeric_columns = df.select_dtypes(include="number").columns.tolist()
            coord_cols = [c for c in df.columns if c.lower() in
                         ("lng", "lon", "longitude", "x", "lat", "latitude", "y")]
            profile.has_coordinates = len(coord_cols) >= 2

        # Detect domain from column names
        all_cols_lower = " ".join(c.lower() for c in profile.columns)
        best_domain = "general"
        best_score = 0
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in all_cols_lower)
            if score > best_score:
                best_score = score
                best_domain = domain
                profile.domain_keywords = [kw for kw in keywords if kw.lower() in all_cols_lower]
        profile.domain = best_domain

    except Exception as e:
        logger.debug("Profile extraction failed for %s: %s", file_path, e)

    return profile


# ---------------------------------------------------------------------------
# Agent Blueprint
# ---------------------------------------------------------------------------

@dataclass
class AgentBlueprint:
    """Blueprint for dynamically composing an LlmAgent."""
    name: str = "DynamicAgent"
    instruction: str = ""
    toolset_names: list[str] = field(default_factory=list)
    model_tier: str = "standard"  # fast, standard, premium
    output_key: str = "dynamic_output"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "instruction_preview": self.instruction[:200],
            "toolset_names": self.toolset_names,
            "model_tier": self.model_tier,
        }


# Domain → toolset mapping
_DOMAIN_TOOLSETS = {
    "landuse": ["ExplorationToolset", "GeoProcessingToolset", "AnalysisToolset",
                "VisualizationToolset", "SpatialStatisticsToolset", "DatabaseToolset",
                "SemanticLayerToolset", "SpatialAnalysisTier2Toolset"],
    "transport": ["ExplorationToolset", "GeoProcessingToolset", "LocationToolset",
                  "VisualizationToolset", "DatabaseToolset"],
    "hydrology": ["ExplorationToolset", "GeoProcessingToolset", "SpatialStatisticsToolset",
                  "VisualizationToolset", "RemoteSensingToolset", "SpatialAnalysisTier2Toolset"],
    "ecology": ["ExplorationToolset", "RemoteSensingToolset", "SpatialStatisticsToolset",
                "VisualizationToolset", "GeoProcessingToolset", "SpatialAnalysisTier2Toolset"],
    "urban": ["ExplorationToolset", "LocationToolset", "GeoProcessingToolset",
              "VisualizationToolset", "DatabaseToolset", "AnalysisToolset"],
    "general": ["ExplorationToolset", "GeoProcessingToolset", "VisualizationToolset",
                "DatabaseToolset", "FileToolset"],
}

# Domain → instruction templates
_DOMAIN_INSTRUCTIONS = {
    "landuse": "你是一个用地分析专家 Agent。数据包含用地类型信息（{keywords}）。"
               "重点关注：用地分类统计、破碎化指数(FFI)、空间自相关分析、分类着色可视化。"
               "如有耕地/林地数据，可考虑布局优化（DRL）。",
    "transport": "你是一个交通网络分析专家 Agent。数据包含交通要素（{keywords}）。"
                 "重点关注：路网连通性、缓冲区分析、POI 可达性、驾车距离计算。",
    "hydrology": "你是一个水文分析专家 Agent。数据包含水文要素（{keywords}）。"
                 "重点关注：流域分析、DEM 地形分析、汇水区划分、空间插值。",
    "ecology": "你是一个生态分析专家 Agent。数据包含生态要素（{keywords}）。"
               "重点关注：NDVI 计算、植被覆盖分析、景观格局指数、热点分析。",
    "urban": "你是一个城市空间分析专家 Agent。数据包含城市要素（{keywords}）。"
             "重点关注：POI 密度分析、空间聚类、服务区分析、地理编码。",
    "general": "你是一个通用 GIS 分析专家 Agent。"
               "请根据数据特征选择合适的分析方法，包括空间统计、可视化、数据质量检查等。",
}


def create_blueprint(profile: DataProfile) -> AgentBlueprint:
    """Create an AgentBlueprint from a DataProfile."""
    domain = profile.domain
    toolset_names = _DOMAIN_TOOLSETS.get(domain, _DOMAIN_TOOLSETS["general"])
    keywords_str = ", ".join(profile.domain_keywords[:5]) or domain

    instruction = _DOMAIN_INSTRUCTIONS.get(domain, _DOMAIN_INSTRUCTIONS["general"])
    instruction = instruction.format(keywords=keywords_str)

    # Add data context to instruction
    context_parts = [instruction]
    if profile.row_count:
        context_parts.append(f"数据量: {profile.row_count} 行, {profile.column_count} 列。")
    if profile.geometry_types:
        context_parts.append(f"几何类型: {', '.join(profile.geometry_types)}。")
    if profile.crs:
        context_parts.append(f"坐标系: {profile.crs}。")
    if profile.numeric_columns:
        context_parts.append(f"数值列: {', '.join(profile.numeric_columns[:5])}。")

    # Select model tier based on complexity
    if profile.row_count > 10000 or len(profile.numeric_columns) > 10:
        model_tier = "premium"
    elif profile.row_count > 1000 or domain != "general":
        model_tier = "standard"
    else:
        model_tier = "fast"

    return AgentBlueprint(
        name=f"Dynamic{domain.capitalize()}Agent",
        instruction="\n".join(context_parts),
        toolset_names=toolset_names,
        model_tier=model_tier,
    )


# ---------------------------------------------------------------------------
# Agent Composition
# ---------------------------------------------------------------------------

def compose_agent(profile: DataProfile):
    """Compose a specialized LlmAgent from a DataProfile.

    Returns an LlmAgent instance or None if composition fails.
    """
    try:
        from google.adk.agents import LlmAgent
        from .custom_skills import _get_toolset_registry
        from .agent import get_model_for_tier

        blueprint = create_blueprint(profile)
        registry = _get_toolset_registry()

        # Instantiate toolsets
        tools = []
        for ts_name in blueprint.toolset_names:
            cls = registry.get(ts_name)
            if cls:
                try:
                    tools.append(cls())
                except Exception as e:
                    logger.debug("Failed to instantiate %s: %s", ts_name, e)

        if not tools:
            return None

        model = get_model_for_tier(blueprint.model_tier)

        agent = LlmAgent(
            name=blueprint.name,
            model=model,
            instruction=blueprint.instruction,
            tools=tools,
            output_key=blueprint.output_key,
        )

        logger.info("Composed agent: %s (domain=%s, tools=%d, model=%s)",
                     blueprint.name, profile.domain, len(tools), blueprint.model_tier)
        return agent

    except Exception as e:
        logger.warning("Agent composition failed: %s", e)
        return None


def compose_pipeline(profiles: list[DataProfile]):
    """Compose a multi-stage pipeline from multiple DataProfiles.

    Returns a SequentialAgent or None.
    """
    if not profiles:
        return None

    try:
        from google.adk.agents import SequentialAgent

        agents = []
        for i, profile in enumerate(profiles):
            agent = compose_agent(profile)
            if agent:
                agent._name = f"Stage{i+1}_{profile.domain}"
                agents.append(agent)

        if not agents:
            return None

        pipeline = SequentialAgent(
            name="DynamicPipeline",
            sub_agents=agents,
        )
        return pipeline

    except Exception as e:
        logger.warning("Pipeline composition failed: %s", e)
        return None
