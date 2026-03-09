"""
Skill Bundles — ADK SkillToolset-based skill groupings.

Migrated from custom SkillBundle dataclass to ADK v1.26 SkillToolset.
Each bundle maps to an ADK Skill loaded from data_agent/skills/ directories.
The existing BaseToolset instances are used alongside SkillToolset
in agent tools=[] lists.

ADK Skills provide three-level incremental loading:
  L1 (metadata) — always loaded, minimal context cost
  L2 (instructions) — loaded when skill is activated
  L3 (references/assets) — loaded on demand
"""
from dataclasses import dataclass, field
from typing import Callable

from google.adk.tools.skill_toolset import SkillToolset

from .exploration_tools import ExplorationToolset
from .geo_processing_tools import GeoProcessingToolset
from .location_tools import LocationToolset
from .analysis_tools import AnalysisToolset
from .visualization_tools import VisualizationToolset
from .database_tools_set import DatabaseToolset
from .file_tools import FileToolset
from .memory_tools import MemoryToolset
from .admin_tools import AdminToolset
from .remote_sensing_tools import RemoteSensingToolset
from .spatial_statistics_tools import SpatialStatisticsToolset
from .semantic_layer_tools import SemanticLayerToolset
from .streaming_tools import StreamingToolset
from .team_tools import TeamToolset
from .datalake_tools import DataLakeToolset


# ---------------------------------------------------------------------------
# Shared filter presets
# ---------------------------------------------------------------------------

AUDIT_TOOLS = [
    "describe_geodataframe", "check_topology",
    "check_field_standards", "check_consistency",
]
TRANSFORM_TOOLS = ["reproject_spatial_data", "engineer_spatial_features"]
DB_READ = ["query_database", "list_tables"]
DB_READ_DESCRIBE = ["query_database", "list_tables", "describe_table"]
DATALAKE_READ = ["list_data_assets", "describe_data_asset", "search_data_assets"]

GENERAL_VIZ = [
    "visualize_geodataframe", "visualize_interactive_map",
    "generate_choropleth", "generate_bubble_map",
    "export_map_png", "compose_map", "generate_heatmap",
    "control_map_layer",
]

SEMANTIC_READONLY = [
    "resolve_semantic_context", "describe_table_semantic",
    "list_semantic_sources", "discover_column_equivalences",
    "export_semantic_model",
]


# ---------------------------------------------------------------------------
# ADK SkillToolset builders
# ---------------------------------------------------------------------------

def build_skill_toolset(name: str) -> SkillToolset:
    """Build a SkillToolset containing a single named skill.

    Args:
        name: Skill directory name (e.g. 'spatial_analysis', 'data_quality').
    """
    from ..skills import load_skill
    return SkillToolset(skills=[load_skill(name)])


def build_all_skills_toolset() -> SkillToolset:
    """Build a single SkillToolset with all 5 domain skills.

    This is the recommended usage for agents that may need any domain —
    the LLM selects which skill to load on demand, keeping context window
    usage minimal via incremental loading.
    """
    from ..skills import load_all_skills
    return SkillToolset(skills=load_all_skills())


# ---------------------------------------------------------------------------
# Legacy SkillBundle — backward compatible interface
# ---------------------------------------------------------------------------

@dataclass
class SkillBundle:
    """A named bundle of toolset instances for agent configuration."""
    name: str
    description: str
    intent_triggers: list[str] = field(default_factory=list)
    _factory: Callable = field(default=lambda: [], repr=False)

    def build_toolsets(self) -> list:
        """Instantiate the toolsets for this bundle."""
        return self._factory()


SPATIAL_ANALYSIS = SkillBundle(
    name="spatial_analysis",
    description="Spatial data exploration, processing, and analysis",
    intent_triggers=["optimization", "governance", "spatial"],
    _factory=lambda: [
        ExplorationToolset(tool_filter=AUDIT_TOOLS),
        GeoProcessingToolset(),
        LocationToolset(),
        RemoteSensingToolset(),
        SpatialStatisticsToolset(),
        AnalysisToolset(),
        DatabaseToolset(tool_filter=DB_READ),
        FileToolset(),
    ],
)

DATA_QUALITY = SkillBundle(
    name="data_quality",
    description="Data governance, auditing, and quality checks",
    intent_triggers=["governance", "audit", "quality"],
    _factory=lambda: [
        ExplorationToolset(tool_filter=AUDIT_TOOLS),
        DatabaseToolset(tool_filter=DB_READ_DESCRIBE),
        FileToolset(),
        SemanticLayerToolset(tool_filter=SEMANTIC_READONLY),
        DataLakeToolset(tool_filter=DATALAKE_READ),
    ],
)

VISUALIZATION = SkillBundle(
    name="visualization",
    description="Map rendering, chart generation, and visual exports",
    intent_triggers=["visualization", "map", "chart"],
    _factory=lambda: [
        VisualizationToolset(tool_filter=GENERAL_VIZ),
    ],
)

DATABASE = SkillBundle(
    name="database",
    description="Database queries, table management, data import, and sharing",
    intent_triggers=["database", "sql", "query", "import", "postgis"],
    _factory=lambda: [
        DatabaseToolset(tool_filter=DB_READ_DESCRIBE + ["share_table", "import_to_postgis"]),
        DataLakeToolset(tool_filter=DATALAKE_READ),
    ],
)

COLLABORATION = SkillBundle(
    name="collaboration",
    description="Team management, memory, admin, and collaboration tools",
    intent_triggers=["team", "share", "collaborate"],
    _factory=lambda: [
        MemoryToolset(),
        AdminToolset(),
        TeamToolset(),
        DataLakeToolset(tool_filter=DATALAKE_READ),
    ],
)


# ---------------------------------------------------------------------------
# Bundle Registry
# ---------------------------------------------------------------------------

ALL_BUNDLES = [SPATIAL_ANALYSIS, DATA_QUALITY, VISUALIZATION, DATABASE, COLLABORATION]

_BUNDLE_MAP = {b.name: b for b in ALL_BUNDLES}


def get_bundle(name: str) -> SkillBundle:
    """Get a bundle by name."""
    return _BUNDLE_MAP[name]


def get_bundles_for_intent(intent: str) -> list[SkillBundle]:
    """Return bundles whose intent_triggers match the given intent."""
    return [b for b in ALL_BUNDLES if intent in b.intent_triggers]


def build_toolsets_for_intent(intent: str) -> list:
    """Build all toolset instances relevant to an intent."""
    toolsets = []
    seen_names = set()
    for bundle in get_bundles_for_intent(intent):
        for ts in bundle.build_toolsets():
            ts_name = type(ts).__name__
            if ts_name not in seen_names:
                toolsets.append(ts)
                seen_names.add(ts_name)
    return toolsets
