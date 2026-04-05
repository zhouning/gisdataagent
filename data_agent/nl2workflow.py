"""
NL2Workflow — Generate executable workflow DAGs from natural language descriptions.

Uses Gemini to parse natural language into structured workflow DAG steps
compatible with the workflow engine's create_workflow() format.
"""
import json
import logging
import re
from typing import Optional

from google import genai as genai_client
from google.genai import types

logger = logging.getLogger("data_agent.nl2workflow")

# Dedicated GenAI client (same pattern as intent_router.py)
_nl2wf_client = genai_client.Client()

# ---------------------------------------------------------------------------
# Valid pipeline types and built-in skill descriptions
# ---------------------------------------------------------------------------

VALID_PIPELINE_TYPES = {"general", "governance", "optimization", "custom_skill"}

BUILTIN_SKILLS = {
    "3d-visualization": "3D model rendering and visualization",
    "advanced-analysis": "Advanced spatial statistics and analytics",
    "buffer-overlay": "Buffer and overlay spatial operations",
    "coordinate-transform": "Coordinate system transformation",
    "data-import-export": "Import/export data in various formats",
    "data-profiling": "Exploratory data profiling and statistics",
    "data-quality-reviewer": "Automated data quality review and scoring",
    "ecological-assessment": "Ecological sensitivity and impact assessment",
    "farmland-compliance": "Farmland protection compliance checking",
    "geocoding": "Address geocoding and reverse geocoding",
    "knowledge-retrieval": "Knowledge base search and retrieval",
    "land-fragmentation": "Land fragmentation analysis (FFI)",
    "multi-source-fusion": "Multi-source data fusion and matching",
    "postgis-analysis": "PostGIS spatial SQL analysis",
    "satellite-imagery": "Satellite/remote sensing image processing",
    "site-selection": "Site selection and suitability analysis",
    "spatial-clustering": "Spatial clustering (DBSCAN, K-means, etc.)",
    "spectral-analysis": "Spectral analysis for remote sensing data",
    "surveying-qc": "Surveying quality control workflow",
    "team-collaboration": "Team collaboration and task management",
    "thematic-mapping": "Thematic map generation and styling",
    "topology-validation": "Topology validation and repair",
    "world-model": "World model LULC prediction and scenario simulation",
}


# ---------------------------------------------------------------------------
# LLM call (separated for easy mocking in tests)
# ---------------------------------------------------------------------------

async def _call_llm(prompt: str) -> str:
    """Call Gemini to generate workflow JSON from the prompt."""
    response = _nl2wf_client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            http_options=types.HttpOptions(
                timeout=60_000,
                retry_options=types.HttpRetryOptions(
                    initial_delay=2.0,
                    attempts=3,
                ),
            ),
        ),
    )
    return response.text.strip()


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_prompt(description: str) -> str:
    """Build the LLM prompt for NL-to-workflow conversion."""
    skills_list = "\n".join(
        f"  - {name}: {desc}" for name, desc in sorted(BUILTIN_SKILLS.items())
    )
    return f"""You are a workflow DAG generator for a GIS Data Agent platform.

Given a natural language description, produce a JSON workflow definition with the following structure:

{{
  "workflow_name": "<short name for the workflow>",
  "description": "<one-line description>",
  "steps": [
    {{
      "step_id": "step_1",
      "label": "<human-readable label>",
      "pipeline_type": "<general|governance|optimization|custom_skill>",
      "prompt": "<the instruction for this step>",
      "depends_on": []
    }},
    {{
      "step_id": "step_2",
      "label": "<label>",
      "pipeline_type": "custom_skill",
      "skill_name": "<skill-name>",
      "prompt": "<instruction>",
      "depends_on": ["step_1"]
    }}
  ],
  "parameters": {{}}
}}

## Available pipeline_types:
- **general**: General queries, SQL, visualization, mapping, analysis, clustering, heatmap, buffer, site selection
- **governance**: Data auditing, quality check, topology fix, standardization, consistency check
- **optimization**: Land use optimization, DRL, FFI calculation, spatial layout planning
- **custom_skill**: Runs a specific built-in skill. Requires "skill_name" field.

## Available skills (for custom_skill pipeline_type):
{skills_list}

## Rules:
1. Each step must have: step_id, label, pipeline_type, prompt, depends_on
2. step_id format: step_1, step_2, step_3, ...
3. depends_on is a list of step_ids this step depends on (empty list for first steps)
4. No circular dependencies allowed
5. Use custom_skill + skill_name when a specific skill clearly matches
6. Use general/governance/optimization for broader tasks
7. The prompt field should be a clear instruction for the agent
8. Keep workflows concise — typically 2-6 steps
9. Output ONLY valid JSON, no markdown code fences, no explanation

## Examples:

Input: "First profile the dataset, then check topology, finally generate a thematic map"
Output:
{{
  "workflow_name": "profile-check-map",
  "description": "Data profiling, topology validation, and thematic mapping pipeline",
  "steps": [
    {{"step_id": "step_1", "label": "Data Profiling", "pipeline_type": "custom_skill", "skill_name": "data-profiling", "prompt": "Profile the dataset and report basic statistics", "depends_on": []}},
    {{"step_id": "step_2", "label": "Topology Check", "pipeline_type": "custom_skill", "skill_name": "topology-validation", "prompt": "Validate topology and report any errors", "depends_on": ["step_1"]}},
    {{"step_id": "step_3", "label": "Thematic Map", "pipeline_type": "custom_skill", "skill_name": "thematic-mapping", "prompt": "Generate a thematic map from the validated data", "depends_on": ["step_2"]}}
  ],
  "parameters": {{}}
}}

Input: "Parallel: run ecological assessment and farmland compliance check, then merge results and optimize land use"
Output:
{{
  "workflow_name": "eco-compliance-optimize",
  "description": "Parallel ecological and compliance assessment followed by optimization",
  "steps": [
    {{"step_id": "step_1", "label": "Ecological Assessment", "pipeline_type": "custom_skill", "skill_name": "ecological-assessment", "prompt": "Run ecological sensitivity assessment on the study area", "depends_on": []}},
    {{"step_id": "step_2", "label": "Farmland Compliance", "pipeline_type": "custom_skill", "skill_name": "farmland-compliance", "prompt": "Check farmland protection compliance", "depends_on": []}},
    {{"step_id": "step_3", "label": "Data Merge", "pipeline_type": "general", "prompt": "Merge ecological assessment and compliance results into a unified dataset", "depends_on": ["step_1", "step_2"]}},
    {{"step_id": "step_4", "label": "Land Use Optimization", "pipeline_type": "optimization", "prompt": "Optimize land use layout based on merged assessment results", "depends_on": ["step_3"]}}
  ],
  "parameters": {{}}
}}

Now generate a workflow for the following description:

"{description}"
"""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class WorkflowValidationError(ValueError):
    """Raised when generated workflow fails validation."""
    pass


def validate_workflow(workflow: dict) -> None:
    """Validate a generated workflow structure. Raises WorkflowValidationError on failure."""
    # Must have steps
    if "steps" not in workflow or not isinstance(workflow["steps"], list):
        raise WorkflowValidationError("Workflow must contain a 'steps' list")

    if len(workflow["steps"]) == 0:
        raise WorkflowValidationError("Workflow must have at least one step")

    step_ids = set()
    for i, step in enumerate(workflow["steps"]):
        # Required fields
        for field in ("step_id", "label", "pipeline_type", "prompt"):
            if field not in step or not step[field]:
                raise WorkflowValidationError(
                    f"Step {i} is missing required field '{field}'"
                )

        # Valid pipeline_type
        if step["pipeline_type"] not in VALID_PIPELINE_TYPES:
            raise WorkflowValidationError(
                f"Step '{step['step_id']}' has invalid pipeline_type "
                f"'{step['pipeline_type']}'. Must be one of {sorted(VALID_PIPELINE_TYPES)}"
            )

        # custom_skill requires skill_name
        if step["pipeline_type"] == "custom_skill" and not step.get("skill_name"):
            raise WorkflowValidationError(
                f"Step '{step['step_id']}' uses custom_skill but is missing 'skill_name'"
            )

        # Unique step_id
        if step["step_id"] in step_ids:
            raise WorkflowValidationError(
                f"Duplicate step_id: '{step['step_id']}'"
            )
        step_ids.add(step["step_id"])

        # Ensure depends_on is a list
        if "depends_on" not in step:
            step["depends_on"] = []
        if not isinstance(step["depends_on"], list):
            raise WorkflowValidationError(
                f"Step '{step['step_id']}' depends_on must be a list"
            )

    # Validate depends_on references
    for step in workflow["steps"]:
        for dep in step["depends_on"]:
            if dep not in step_ids:
                raise WorkflowValidationError(
                    f"Step '{step['step_id']}' depends on unknown step '{dep}'"
                )

    # Check for circular dependencies via topological sort
    _check_cycles(workflow["steps"])


def _check_cycles(steps: list) -> None:
    """Detect circular dependencies using Kahn's algorithm."""
    adj: dict[str, list[str]] = {s["step_id"]: [] for s in steps}
    in_degree: dict[str, int] = {s["step_id"]: 0 for s in steps}

    for step in steps:
        for dep in step.get("depends_on", []):
            adj[dep].append(step["step_id"])
            in_degree[step["step_id"]] += 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    visited = 0

    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(steps):
        raise WorkflowValidationError("Circular dependency detected in workflow steps")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_workflow(description: str, user_id: str = "anonymous") -> dict:
    """
    Parse a natural language workflow description and generate a DAG.

    Args:
        description: Natural language description of the desired workflow.
        user_id: User ID for context.

    Returns:
        dict with keys: workflow_name, description, steps, parameters, explanation
    """
    if not description or not description.strip():
        raise WorkflowValidationError("Description cannot be empty")

    prompt = _build_prompt(description.strip())
    raw_response = await _call_llm(prompt)

    # Strip markdown code fences if present
    cleaned = raw_response
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()

    # Parse JSON
    try:
        workflow = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s", raw_response[:500])
        raise WorkflowValidationError(f"LLM returned invalid JSON: {e}") from e

    # Ensure top-level fields
    if "workflow_name" not in workflow:
        workflow["workflow_name"] = "nl-generated-workflow"
    if "description" not in workflow:
        workflow["description"] = description[:200]
    if "parameters" not in workflow:
        workflow["parameters"] = {}

    # Validate
    validate_workflow(workflow)

    # Add explanation for the API response
    workflow["_explanation"] = (
        f"Generated {len(workflow['steps'])}-step workflow from natural language. "
        f"Steps: {', '.join(s['label'] for s in workflow['steps'])}."
    )

    return workflow
