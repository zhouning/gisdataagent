"""CLI entry point for gis-skill command."""

import argparse
import json
import os
import sys


def cmd_validate(args):
    """Validate a skill directory."""
    from .validator import validate_skill_directory

    path = os.path.abspath(args.path)
    result = validate_skill_directory(path)

    if result["valid"]:
        print(f"OK Skill '{result.get('skill_name', '?')}' is valid")
        if result.get("warnings"):
            for w in result["warnings"]:
                print(f"  WARNING: {w}")
    else:
        print("FAIL Skill validation failed")
        for e in result.get("errors", []):
            print(f"  ERROR: {e}")
        for w in result.get("warnings", []):
            print(f"  WARNING: {w}")

    return 0 if result["valid"] else 1


def cmd_list(args):
    """List skills in a directory."""
    from .loader import discover_skills

    path = os.path.abspath(args.path)
    skills = discover_skills(path)

    if not skills:
        print(f"No skills found in {path}")
        return 0

    print(f"Found {len(skills)} skills in {path}:\n")
    for s in skills:
        if s.get("error"):
            print(f"  FAIL {s['name']} (load error)")
        else:
            kw = ", ".join(s.get("trigger_keywords", [])[:3])
            print(
                f"  {s['name']} [{s.get('pattern', '?')}] -- {s.get('description', '')[:60]}"
            )
            if kw:
                print(f"    keywords: {kw}")
    return 0


def cmd_new(args):
    """Scaffold a new skill directory."""
    name = args.name
    target = os.path.join(os.getcwd(), name)

    if os.path.exists(target):
        print(f"Error: Directory '{name}' already exists")
        return 1

    os.makedirs(target)

    skill_md = f"""---
name: {name}
description: TODO -- describe what this skill does
version: "1.0"
category: general
pattern: command
trigger_keywords:
  - {name.replace('-', ' ')}
toolsets:
  - ExplorationToolset
model_tier: standard
---

# {name}

## Purpose

TODO -- explain when this skill should be activated and what it does.

## Instructions

TODO -- provide detailed instructions for the LLM agent.
"""

    with open(os.path.join(target, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_md)

    # Create optional directories
    os.makedirs(os.path.join(target, "references"), exist_ok=True)
    os.makedirs(os.path.join(target, "assets"), exist_ok=True)

    print(f"Created skill scaffold: {target}/")
    print(f"  - SKILL.md (edit this)")
    print(f"  - references/ (optional reference docs)")
    print(f"  - assets/ (optional data files)")
    return 0


def cmd_info(args):
    """Show detailed info about a skill."""
    from .loader import load_skill

    path = os.path.abspath(args.path)
    try:
        skill = load_skill(path)
        print(f"Name: {skill.metadata.name}")
        print(f"Description: {skill.metadata.description}")
        print(f"Pattern: {skill.metadata.pattern}")
        print(f"Model tier: {skill.metadata.model_tier}")
        print(f"Trigger keywords: {', '.join(skill.metadata.trigger_keywords)}")
        print(f"Toolsets: {', '.join(skill.metadata.toolsets)}")
        print(f"Instruction length: {len(skill.instruction)} chars")
        print(f"Source: {skill.source_path}")
    except Exception as e:
        print(f"Error loading skill: {e}")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="gis-skill", description="GIS Skill SDK CLI"
    )
    sub = parser.add_subparsers(dest="command")

    p_validate = sub.add_parser("validate", help="Validate a skill directory")
    p_validate.add_argument("path", help="Path to skill directory")

    p_list = sub.add_parser("list", help="List skills in a directory")
    p_list.add_argument("path", help="Path to skills base directory")

    p_new = sub.add_parser("new", help="Create a new skill scaffold")
    p_new.add_argument("name", help="Skill name (kebab-case)")

    p_info = sub.add_parser("info", help="Show skill details")
    p_info.add_argument("path", help="Path to skill directory or SKILL.md")

    args = parser.parse_args()

    if args.command == "validate":
        sys.exit(cmd_validate(args))
    elif args.command == "list":
        sys.exit(cmd_list(args))
    elif args.command == "new":
        sys.exit(cmd_new(args))
    elif args.command == "info":
        sys.exit(cmd_info(args))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
