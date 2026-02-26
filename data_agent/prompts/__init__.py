"""
Prompt loading utilities.
Replaces the single prompts.yaml with domain-specific YAML files.
"""
import os
import yaml

_DIR = os.path.dirname(__file__)
_cache: dict = {}


def load_prompts(domain: str) -> dict:
    """Load all prompts from a domain-specific YAML file."""
    if domain not in _cache:
        path = os.path.join(_DIR, f"{domain}.yaml")
        with open(path, encoding="utf-8") as f:
            _cache[domain] = yaml.safe_load(f)
    return _cache[domain]


def get_prompt(domain: str, key: str) -> str:
    """Get a single prompt by domain and key."""
    return load_prompts(domain)[key]
