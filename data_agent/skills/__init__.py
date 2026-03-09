"""
ADK Skills — Domain-expertise skill definitions.

Each subdirectory contains a SKILL.md (instructions + frontmatter)
and optional references/ and assets/ directories.

Skills are loaded via load_skill_from_dir() and wrapped in SkillToolset
for agent integration. Incremental loading: L1 metadata always loaded,
L2 instructions + L3 resources loaded on activation.
"""
import pathlib

from google.adk.skills import load_skill_from_dir

_SKILLS_DIR = pathlib.Path(__file__).parent


def load_skill(name: str):
    """Load a single skill by directory name."""
    return load_skill_from_dir(_SKILLS_DIR / name)


def load_all_skills() -> list:
    """Load all skills from subdirectories that contain SKILL.md."""
    return [
        load_skill_from_dir(p)
        for p in sorted(_SKILLS_DIR.iterdir())
        if p.is_dir() and (p / "SKILL.md").exists()
    ]
