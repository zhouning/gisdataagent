"""
Prompt loading utilities.
Replaces the single prompts.yaml with domain-specific YAML files.
Supports _version and _changelog metadata in each YAML.
"""
import logging
import os

import yaml

_DIR = os.path.dirname(__file__)
_cache: dict = {}
_versions: dict[str, str] = {}

logger = logging.getLogger(__name__)


def load_prompts(domain: str) -> dict:
    """Load all prompts from a domain-specific YAML file."""
    if domain not in _cache:
        path = os.path.join(_DIR, f"{domain}.yaml")
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        version = data.pop("_version", "unknown")
        data.pop("_changelog", None)
        _cache[domain] = data
        _versions[domain] = version
    return _cache[domain]


def get_prompt(domain: str, key: str, env: str = "prod") -> str:
    """Get a single prompt by domain and key. Tries DB first, falls back to YAML."""
    try:
        from ..prompt_registry import PromptRegistry
        registry = PromptRegistry()
        return registry.get_prompt(domain, key, env)
    except Exception:
        return load_prompts(domain)[key]


def get_prompt_version(domain: str) -> str:
    """Get the version string for a loaded domain."""
    load_prompts(domain)
    return _versions.get(domain, "unknown")


def log_prompt_versions():
    """Load all prompt domains and log their versions."""
    for domain in ("optimization", "planner", "general"):
        load_prompts(domain)
    versions_str = ", ".join(f"{d}={_versions[d]}" for d in sorted(_versions))
    logger.info("[Prompt] %s", versions_str)
    return dict(_versions)
