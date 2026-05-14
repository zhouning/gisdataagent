"""CLI for `gis-agent standards ...` subcommands.

Subcommands:
  init   Generate a semantic-layer column config from a docx 国标 table.
  diff   Compare derived config against a hand-written register_cq_semantic
         style file.
  list   List all docx tables available for derivation.

Examples:
  gis-agent standards list
  gis-agent standards list --module 02
  gis-agent standards init --pg-table cq_land_use_dltb --docx-table DLTB
  gis-agent standards init --docx-table DLTB --format yaml --out dltb_config.yaml
  gis-agent standards diff --pg-table cq_land_use_dltb --docx-table DLTB \
      --against scripts/nl2sql_bench_cq/register_cq_semantic.py
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from .semantic_config_generator import (
    generate_semantic_config,
    derive_column_meta,
)

_COMPILED = Path(__file__).resolve().parent / "compiled_docx"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _find_module_for_table(docx_table_code: str) -> str | None:
    """Scan compiled_docx/*.yaml to find which module contains the given table."""
    code = docx_table_code.strip().upper()
    for yp in sorted(_COMPILED.glob("*.yaml")):
        if yp.name.startswith("_"):
            continue
        try:
            doc = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for ft in doc.get("field_tables", []):
            if (ft.get("table_code") or "").strip().upper() == code:
                return yp.name
    return None


def _list_tables(module_filter: str | None = None) -> list[dict]:
    out = []
    for yp in sorted(_COMPILED.glob("*.yaml")):
        if yp.name.startswith("_"):
            continue
        try:
            doc = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        module = doc.get("module", yp.stem)
        if module_filter and module_filter not in module:
            continue
        for ft in doc.get("field_tables", []):
            code = (ft.get("table_code") or "").strip()
            if not code:
                continue
            out.append({
                "module": module,
                "table_code": code,
                "table_name_cn": ft.get("table_name_cn", ""),
                "field_count": len(ft.get("fields") or []),
            })
    return out


def _load_pg_columns_from_dump(dump_path: Path, pg_table: str) -> list[str] | None:
    """Best-effort: parse CREATE TABLE from a SQL dump file."""
    if not dump_path.is_file():
        return None
    import re
    text = dump_path.read_text(encoding="utf-8")
    m = re.search(
        rf"CREATE TABLE\s+(?:public\.)?{re.escape(pg_table)}\s*\((.*?)\);",
        text, re.S | re.I,
    )
    if not m:
        return None
    cols = []
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line or line.upper().startswith("CONSTRAINT"):
            continue
        parts = line.split()
        if parts:
            cols.append(parts[0].strip('"'))
    return cols or None


def _load_hand_written_register(py_path: Path, pg_table: str) -> dict | None:
    """Dynamically import a register_*.py file and pull COLUMNS[pg_table]."""
    if not py_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_hand_register", py_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    cols_dict = getattr(mod, "COLUMNS", None)
    if not isinstance(cols_dict, dict):
        return None
    return cols_dict.get(pg_table)


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #

def _cmd_list(args: argparse.Namespace) -> int:
    rows = _list_tables(args.module)
    if not rows:
        print(f"No tables found (module filter: {args.module!r})")
        return 1
    print(f"{'module':30s}  {'code':18s}  {'fields':6s}  table_name_cn")
    print("-" * 100)
    for r in rows:
        print(f"  {r['module'][:28]:28s}  {r['table_code'][:16]:16s}  {r['field_count']:6d}  {r['table_name_cn']}")
    print(f"\n({len(rows)} tables)")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    docx_code = args.docx_table.strip().upper()
    module_yaml = args.module
    if not module_yaml:
        module_yaml = _find_module_for_table(docx_code)
        if not module_yaml:
            print(f"ERROR: table code {docx_code!r} not found in any compiled_docx/ module")
            print(f"       Run: gis-agent standards list  to see available tables.")
            return 1
        print(f"[auto-detected module: {module_yaml}]", file=sys.stderr)

    # Determine PG column set
    pg_cols: list[str] | None = None
    if args.pg_columns:
        pg_cols = [c.strip() for c in args.pg_columns.split(",") if c.strip()]
    elif args.dump:
        pg_cols = _load_pg_columns_from_dump(Path(args.dump), args.pg_table or "")
        if pg_cols is None:
            print(f"ERROR: could not parse {args.pg_table!r} from {args.dump}")
            return 1

    result = generate_semantic_config(module_yaml, docx_code, pg_cols)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    # Strip provenance keys from derived dicts when emitting
    clean = {}
    for col, meta in result["derived"].items():
        clean[col] = {k: v for k, v in meta.items() if not k.startswith("_")}

    out: str
    if args.format == "yaml":
        out = yaml.safe_dump(clean, allow_unicode=True, sort_keys=False)
    elif args.format == "json":
        out = json.dumps(clean, ensure_ascii=False, indent=2)
    else:  # py — register_cq_semantic style
        lines = []
        lines.append(f"# Generated from docx 国标 — module={module_yaml}, table_code={docx_code}")
        lines.append(f"# Source: {result.get('source_caption','')}")
        lines.append(f"# docx fields total: {result.get('docx_field_count', 0)};  "
                     f"PG columns derived: {len(clean)};  "
                     f"docx-only (governance gap): {len(result.get('docx_only', []))}")
        lines.append("")
        pg_table_name = args.pg_table or "<table>"
        lines.append(f'"{pg_table_name}": {{')
        for col, meta in clean.items():
            aliases_str = json.dumps(meta.get("aliases", []), ensure_ascii=False)
            domain_str = repr(meta.get("domain"))
            unit_str = repr(meta.get("unit", ""))
            desc_str = repr(meta.get("desc", ""))
            lines.append(f'    "{col}": {{"domain": {domain_str}, '
                         f'"aliases": {aliases_str}, '
                         f'"unit": {unit_str}, '
                         f'"desc": {desc_str}}},')
        lines.append("},")
        if result.get("docx_only"):
            lines.append("")
            lines.append("# --- 治理 gap: 国标定义但实际表未实现的字段 ---")
            for c in result["docx_only"]:
                lines.append(f"# - {c}")
        out = "\n".join(lines)

    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(out)

    # Summary on stderr
    summary = {
        "docx_field_count": result["docx_field_count"],
        "derived_count": len(clean),
        "docx_only_count": len(result.get("docx_only", [])),
        "pg_only_count": len(result.get("pg_only", [])),
    }
    print(f"\n# Summary: {json.dumps(summary, ensure_ascii=False)}", file=sys.stderr)
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    docx_code = args.docx_table.strip().upper()
    pg_table = args.pg_table

    module_yaml = args.module or _find_module_for_table(docx_code)
    if not module_yaml:
        print(f"ERROR: table code {docx_code!r} not found")
        return 1

    hand = _load_hand_written_register(Path(args.against), pg_table)
    if hand is None:
        print(f"ERROR: cannot find {pg_table!r} in COLUMNS of {args.against}")
        return 1

    pg_cols = list(hand.keys())
    result = generate_semantic_config(module_yaml, docx_code, pg_cols)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    rows = []
    only_hand = []
    only_docx = result["docx_only"]
    for col, hand_meta in hand.items():
        derived = result["derived"].get(col)
        if derived is None:
            only_hand.append(col)
            continue
        h_alias = set(hand_meta.get("aliases", []) or [])
        d_alias = set(derived.get("aliases", []) or [])
        rows.append({
            "col": col,
            "domain_match": hand_meta.get("domain") == derived.get("domain"),
            "unit_match": hand_meta.get("unit", "") == derived.get("unit", ""),
            "aliases_common": len(h_alias & d_alias),
            "aliases_hand_only": len(h_alias - d_alias),
            "aliases_derived_only": len(d_alias - h_alias),
        })

    n = len(rows)
    dom = sum(1 for r in rows if r["domain_match"])
    unit = sum(1 for r in rows if r["unit_match"])

    print(f"Diff: {pg_table} (hand) ↔ docx {docx_code}")
    print(f"  diffable: {n}, hand-only: {len(only_hand)}, docx-only (治理 gap): {len(only_docx)}")
    print(f"  domain match: {dom}/{n} ({100*dom/max(1,n):.0f}%)")
    print(f"  unit match:   {unit}/{n} ({100*unit/max(1,n):.0f}%)")
    print(f"  aliases avg common: {sum(r['aliases_common'] for r in rows)/max(1,n):.1f}")
    print()
    print(f"{'col':16s} {'dom':5s} {'unit':5s}  共有  人工独有  docx独有")
    for r in rows:
        print(f"  {r['col'][:14]:14s} "
              f"{'✓' if r['domain_match'] else '✗':5s} "
              f"{'✓' if r['unit_match'] else '✗':5s}  "
              f"{r['aliases_common']:3d}     "
              f"{r['aliases_hand_only']:3d}      "
              f"{r['aliases_derived_only']:3d}")
    if only_docx:
        print(f"\nDocx-only 国标字段 ({len(only_docx)} 个治理 gap):")
        print("  " + ", ".join(only_docx))
    return 0


# --------------------------------------------------------------------------- #
# Dispatcher (called from gis-agent CLI)
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="gis-agent standards",
        description="Standard-driven semantic-layer configuration helpers.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List available docx tables.")
    p_list.add_argument("--module", help="Filter by module substring (e.g. '02')")

    p_init = sub.add_parser("init", help="Generate semantic-layer config from a docx table.")
    p_init.add_argument("--docx-table", required=True, help="Docx 国标 table code, e.g. DLTB")
    p_init.add_argument("--pg-table", help="PG physical table name (for header in py output)")
    p_init.add_argument("--module", help="Module YAML filename (auto-detected if omitted)")
    p_init.add_argument("--pg-columns", help="Comma-separated PG column names (filters output to these)")
    p_init.add_argument("--dump", help="Path to a .sql dump file to parse PG columns from")
    p_init.add_argument("--format", choices=["py", "yaml", "json"], default="py")
    p_init.add_argument("--out", help="Write to file instead of stdout")

    p_diff = sub.add_parser("diff", help="Diff docx-derived config vs hand-written register_*.py.")
    p_diff.add_argument("--docx-table", required=True)
    p_diff.add_argument("--pg-table", required=True)
    p_diff.add_argument("--module")
    p_diff.add_argument("--against", required=True,
                        help="Path to a python file exposing COLUMNS[pg_table] dict")

    args = p.parse_args(argv)
    if args.cmd == "list":
        return _cmd_list(args)
    if args.cmd == "init":
        return _cmd_init(args)
    if args.cmd == "diff":
        return _cmd_diff(args)
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
