# GIS Skill SDK — Specification v1.0

## Overview

The GIS Skill SDK allows external developers to create custom Skills
for the GIS Data Agent platform. Skills are packaged as directories
with a manifest file and optional Python code.

## Directory Structure

```
my-skill/
├── skill.yaml          # Required: manifest
├── instruction.md      # Required: agent instructions
├── README.md           # Optional: documentation
├── requirements.txt    # Optional: Python dependencies
└── tools/              # Optional: custom tool functions
    └── my_tool.py
```

## Manifest Format (skill.yaml)

```yaml
name: my-skill-name           # kebab-case, unique per publisher
version: "1.0.0"              # semver
description: "Short description"
author: "Publisher Name"
license: "MIT"

# Agent configuration
instruction_file: instruction.md
model_tier: standard           # fast | standard | premium
toolset_names:                 # built-in toolsets to include
  - DatabaseToolset
  - VisualizationToolset

# Trigger configuration
trigger_keywords:
  - "my keyword"
  - "another trigger"

# Dependencies on other skills
depends_on:                    # skill names (resolved at install time)
  - base-analysis-skill

# Webhook notifications
webhooks:
  - url: "https://example.com/hook"
    events:
      - "skill.invoked"
      - "skill.completed"

# Metadata
metadata:
  domain: "hydrology"
  version: "1.0.0"
  intent_triggers: "水文,流域"
```

## Installation

Skills can be installed via:

1. **Upload**: Upload the skill directory as a ZIP file
2. **Registry**: Install from the Marketplace Gallery
3. **CLI**: `gis-skill install ./my-skill/` (future)

## API

The platform provides these SDK functions:

```python
from gis_skill_sdk import register_skill, SkillContext

@register_skill("my-skill-name")
def run(ctx: SkillContext):
    # ctx.user_id — current user
    # ctx.session_id — current session
    # ctx.tools — available toolsets
    # ctx.memory — spatial memory access
    # ctx.data_catalog — data catalog queries
    pass
```

## Validation

Skills are validated at install time:
- Manifest schema check
- Instruction length limits (max 10,000 chars)
- Toolset name validation against registered toolsets
- Dependency resolution (DAG cycle detection)
- Python code AST safety check (if custom tools included)
