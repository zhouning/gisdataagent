"""Data-model renderer — turn std_data_element rows + value domains into
CDM/LDM/PDM JSON plus PostgreSQL DDL.

The contract:

  build_model(elements=, value_domains=, terms=)  ->  IR  (dict)
  render_cdm(IR)                                  ->  CDM JSON
  render_ldm(IR)                                  ->  LDM JSON
  render_pdm(IR)                                  ->  PDM JSON
  render_ddl(IR, dialect='postgresql')            ->  text

The IR (intermediate representation) is structured so adding a new dialect
(MySQL / Oracle / SparkSQL) only means writing a new render_ddl_<dialect>;
the entity / attribute model stays put.

This module is intentionally pure: no DB calls, no logging, no ADK. Tests
hand it dicts and assert against return values. Side effects live in the
strategy layer (data_model.py).
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from typing import Any, Iterable


# Default size for unknown-length code/varchar columns. Lifted to a module
# constant so future ALTER TABLE std_data_element ADD COLUMN max_length
# can drop in cleanly.
DEFAULT_CODE_LENGTH = 64

# Default decimal precision when std_data_element doesn't carry it.
DEFAULT_NUMERIC_PRECISION = 18
DEFAULT_NUMERIC_SCALE = 4

# Default geometry SRID + type when not explicitly carried. CGCS2000 (4490)
# would be more correct for Chinese national standards but the project's
# existing semantic layer already standardises on 4326 for cq_* tables, and
# the per-element unit field can override.
DEFAULT_GEOMETRY_SRID = 4326
DEFAULT_GEOMETRY_TYPE = "Geometry"


_LDM_TYPE_BY_REPRCLASS: dict[str, str] = {
    "code":     "string",
    "text":     "string",
    "integer":  "integer",
    "decimal":  "decimal",
    "datetime": "datetime",
    "boolean":  "boolean",
    "geometry": "geometry",
}


def _humanize(name: str) -> str:
    """Best-effort fallback display name from a snake_case identifier."""
    return name.replace("_", " ").strip().title() if name else ""


def _resolve_zh_name(*, fallback: str, candidates: Iterable[str | None]) -> str:
    for c in candidates:
        if c:
            return c
    return _humanize(fallback)


def _quote_ident(name: str) -> str:
    """Always-safe PostgreSQL identifier quoting. Uppercase / mixed-case /
    Chinese identifiers all need quoting; we just always quote so the DDL
    doesn't depend on case-folding rules."""
    return '"' + name.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _physical_type_for(*, repr_class: str | None, datatype: str | None,
                      domain_kind: str | None,
                      unit: str | None) -> str:
    """Decide the PostgreSQL physical type for a single attribute."""
    rc = repr_class or "text"
    if rc == "code":
        return f"VARCHAR({DEFAULT_CODE_LENGTH})"
    if rc == "text":
        return "TEXT"
    if rc == "integer":
        return "BIGINT"
    if rc == "decimal":
        return f"NUMERIC({DEFAULT_NUMERIC_PRECISION},{DEFAULT_NUMERIC_SCALE})"
    if rc == "datetime":
        return "TIMESTAMPTZ"
    if rc == "boolean":
        return "BOOLEAN"
    if rc == "geometry":
        # `unit` may carry a SRID like "EPSG:4490" or geometry hint like
        # "POLYGON@4490"; if so respect it. Otherwise fall back.
        srid = DEFAULT_GEOMETRY_SRID
        gtype = DEFAULT_GEOMETRY_TYPE
        if unit:
            u = unit.strip()
            if "@" in u:
                gpart, _, spart = u.partition("@")
                if gpart:
                    gtype = gpart
                if spart:
                    try:
                        srid = int(spart.replace("EPSG:", "").strip())
                    except ValueError:
                        pass
            elif u.upper().startswith("EPSG:"):
                try:
                    srid = int(u.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif u.upper() in ("POINT", "LINESTRING", "POLYGON",
                               "MULTIPOINT", "MULTILINESTRING",
                               "MULTIPOLYGON", "GEOMETRYCOLLECTION"):
                gtype = u.upper().title() if u.isupper() else u
        return f"GEOMETRY({gtype}, {srid})"
    # Fallback: keep the source datatype if one was provided, else TEXT.
    return (datatype or "TEXT").upper()


def _logical_type_for(repr_class: str | None) -> str:
    return _LDM_TYPE_BY_REPRCLASS.get(repr_class or "text", "string")


def _check_constraint_for(*, column: str, repr_class: str | None,
                          domain_kind: str | None,
                          domain_items: list[dict] | None) -> str | None:
    """Build a single CHECK clause for a column. Returns the body without
    `CHECK` / parens — caller wraps appropriately."""
    if not domain_kind or not domain_items:
        return None
    qcol = _quote_ident(column)

    if domain_kind == "enumeration":
        values = [it.get("value") for it in domain_items if it.get("value")]
        if not values:
            return None
        listed = ", ".join(_quote_literal(v) for v in values)
        return f"{qcol} IN ({listed})"

    if domain_kind == "pattern":
        # First non-empty value is the regex.
        for it in domain_items:
            v = it.get("value")
            if v:
                return f"{qcol} ~ {_quote_literal(v)}"
        return None

    if domain_kind == "range":
        # Items convention: at most two with label_zh in {'min','max','low','high'}
        # — gracefully skip if shape unknown.
        low = high = None
        for it in domain_items:
            label = (it.get("label_zh") or it.get("label_en") or "").lower()
            v = it.get("value")
            if v is None:
                continue
            if label in ("min", "low", "下限", "minimum"):
                low = v
            elif label in ("max", "high", "上限", "maximum"):
                high = v
        if low is not None and high is not None:
            return f"{qcol} BETWEEN {low} AND {high}"
        if low is not None:
            return f"{qcol} >= {low}"
        if high is not None:
            return f"{qcol} <= {high}"
        return None

    # external_codelist / unknown — defer (rules engine still handles it).
    return None


def build_model(*, elements: list[dict],
                value_domains: dict[str, dict],
                terms: dict[str, dict] | None = None) -> dict:
    """Assemble the IR.

    Args:
        elements: rows from std_data_element joined left with std_value_domain.
            Required keys per element:
              id, name_zh, name_en, code, definition,
              representation_class, datatype, unit, value_domain_id,
              obligation, bound_table, bound_column, term_id
        value_domains: {value_domain_id: {kind, code, name, items: [...]}}.
            items is a list of {value, label_zh, label_en, ordinal} sorted
            by ordinal.
        terms: optional {term_id: {name_zh, name_en, definition}} for pretty
            naming on the CDM/LDM layer.

    Returns:
        Dict shaped like:
          {
            "entities": [
              {
                "physical_table": "cq_dltb",
                "name_zh": "...",
                "name_en": "...",
                "attributes": [...]
              }
            ],
            "warnings": [...],
            "stats": {"entity_count": N, "attribute_count": M,
                      "constraint_count": K}
          }
    """
    terms = terms or {}
    warnings: list[str] = []

    # Group elements by bound_table. Skip un-bound ones — they can't go into
    # a physical model. Caller decides whether to surface that as a warning.
    by_table: dict[str, list[dict]] = defaultdict(list)
    skipped = 0
    for el in elements:
        bt = el.get("bound_table")
        bc = el.get("bound_column")
        if not bt or not bc:
            skipped += 1
            continue
        by_table[bt].append(el)
    if skipped:
        warnings.append(
            f"{skipped} data_element rows skipped (no bound_table/column)")

    entities: list[dict] = []
    constraint_count = 0

    for table_name in sorted(by_table.keys()):
        rows = by_table[table_name]
        # Pretty name: prefer the term linked to the *first* element that
        # has one; fall back to humanised table name. We deliberately don't
        # try to pick "the most common" term — spec doesn't promise that.
        entity_name_zh = None
        entity_name_en = None
        for r in rows:
            tid = r.get("term_id")
            if tid and tid in terms:
                entity_name_zh = terms[tid].get("name_zh")
                entity_name_en = terms[tid].get("name_en")
                break
        if not entity_name_zh:
            entity_name_zh = _humanize(table_name)
        if not entity_name_en:
            entity_name_en = table_name

        attrs: list[dict] = []
        for el in rows:
            domain_id = el.get("value_domain_id")
            domain = value_domains.get(str(domain_id)) if domain_id else None
            domain_kind = domain.get("kind") if domain else None
            domain_items = domain.get("items") if domain else None
            domain_code = domain.get("code") if domain else None

            repr_class = el.get("representation_class")
            phys_type = _physical_type_for(
                repr_class=repr_class,
                datatype=el.get("datatype"),
                domain_kind=domain_kind,
                unit=el.get("unit"),
            )
            logical_type = _logical_type_for(repr_class)

            check = _check_constraint_for(
                column=el["bound_column"],
                repr_class=repr_class,
                domain_kind=domain_kind,
                domain_items=domain_items,
            )
            constraints: list[str] = []
            if check:
                constraints.append(f"CHECK ({check})")
                constraint_count += 1

            obligation = el.get("obligation", "optional")
            nullable = obligation != "mandatory"
            if not nullable:
                constraint_count += 1  # NOT NULL counts too

            comment = (el.get("name_zh") or "").strip() or None

            attrs.append({
                "physical_column": el["bound_column"],
                "name_zh": el.get("name_zh") or el["bound_column"],
                "name_en": el.get("name_en") or el["bound_column"],
                "code": el.get("code"),
                "definition": (el.get("definition") or "").strip() or None,
                "representation_class": repr_class,
                "logical_type": logical_type,
                "physical_type": phys_type,
                "nullable": nullable,
                "is_geometry": repr_class == "geometry",
                "constraints": constraints,
                "comment": comment,
                "data_element_id": str(el["id"]),
                "value_domain_code": domain_code,
                "obligation": obligation,
            })

        # Dedup by physical_column — same standard reused for two elements
        # is a real edge case (see plan §6 risk #2). Keep first; warn.
        seen: set[str] = set()
        deduped: list[dict] = []
        for a in attrs:
            if a["physical_column"] in seen:
                warnings.append(
                    f"{table_name}.{a['physical_column']}: multiple "
                    f"data_element definitions, kept first")
                continue
            seen.add(a["physical_column"])
            deduped.append(a)

        entities.append({
            "physical_table": table_name,
            "name_zh": entity_name_zh,
            "name_en": entity_name_en,
            "attributes": deduped,
        })

    stats = {
        "entity_count": len(entities),
        "attribute_count": sum(len(e["attributes"]) for e in entities),
        "constraint_count": constraint_count,
    }
    return {"entities": entities, "warnings": warnings, "stats": stats}


def render_cdm(model: dict) -> dict:
    """Conceptual layer — entity + Chinese name + attribute names only.
    No technical detail. Intended for stakeholder review."""
    entities = []
    for e in model.get("entities", []):
        entities.append({
            "name_zh": e["name_zh"],
            "name_en": e["name_en"],
            "attributes": [
                {"name_zh": a["name_zh"], "code": a.get("code")}
                for a in e["attributes"]
            ],
        })
    return {"layer": "CDM", "entities": entities}


def render_ldm(model: dict) -> dict:
    """Logical layer — adds logical_type + nullable. Still PG-agnostic."""
    entities = []
    for e in model.get("entities", []):
        entities.append({
            "name_zh": e["name_zh"],
            "name_en": e["name_en"],
            "physical_table": e["physical_table"],
            "attributes": [
                {
                    "name_zh": a["name_zh"],
                    "name_en": a["name_en"],
                    "code": a.get("code"),
                    "logical_type": a["logical_type"],
                    "nullable": a["nullable"],
                    "is_geometry": a["is_geometry"],
                    "value_domain_code": a.get("value_domain_code"),
                }
                for a in e["attributes"]
            ],
        })
    return {"layer": "LDM", "entities": entities}


def render_pdm(model: dict) -> dict:
    """Physical layer — full PG types and constraints, ready for DDL gen."""
    entities = []
    for e in model.get("entities", []):
        entities.append({
            "physical_table": e["physical_table"],
            "name_zh": e["name_zh"],
            "name_en": e["name_en"],
            "attributes": [
                {
                    "physical_column": a["physical_column"],
                    "name_zh": a["name_zh"],
                    "physical_type": a["physical_type"],
                    "nullable": a["nullable"],
                    "is_geometry": a["is_geometry"],
                    "constraints": a["constraints"],
                    "comment": a["comment"],
                    "code": a.get("code"),
                    "value_domain_code": a.get("value_domain_code"),
                }
                for a in e["attributes"]
            ],
        })
    return {"layer": "PDM", "dialect": "postgresql", "entities": entities}


def render_ddl(model: dict, *, dialect: str = "postgresql") -> str:
    """Render a copy-pasteable DDL script.

    Currently only PostgreSQL is supported. Future MySQL/Oracle/SparkSQL
    dialects will branch on `dialect` here.
    """
    if dialect != "postgresql":
        raise ValueError(f"unsupported dialect: {dialect}")

    parts: list[str] = []
    parts.append(
        "-- Generated by Standards Platform / to_data_model strategy.\n"
        "-- Dialect: PostgreSQL + PostGIS.\n"
        "-- This DDL describes the *intended* schema. To apply against an\n"
        "-- existing populated table, translate to ALTER TABLE statements.\n"
    )
    for e in model.get("entities", []):
        tbl_q = _quote_ident(e["physical_table"])
        col_lines: list[str] = []
        post_stmts: list[str] = []  # COMMENT ON / CREATE INDEX

        for a in e["attributes"]:
            col_q = _quote_ident(a["physical_column"])
            line_parts = [f"    {col_q} {a['physical_type']}"]
            if not a["nullable"]:
                line_parts.append("NOT NULL")
            for c in a["constraints"]:
                line_parts.append(c)
            col_lines.append(" ".join(line_parts))

            if a["comment"]:
                post_stmts.append(
                    f"COMMENT ON COLUMN {tbl_q}.{col_q} IS "
                    f"{_quote_literal(a['comment'])};"
                )
            if a["is_geometry"]:
                # GIST index for spatial queries.
                idx_name = (
                    f"idx_{e['physical_table']}_{a['physical_column']}_gist"
                ).lower()
                post_stmts.append(
                    f"CREATE INDEX IF NOT EXISTS "
                    f"{_quote_ident(idx_name)} ON {tbl_q} USING GIST "
                    f"({col_q});"
                )

        if not col_lines:
            continue

        ddl = (
            f"CREATE TABLE IF NOT EXISTS {tbl_q} (\n"
            + ",\n".join(col_lines)
            + "\n);\n"
        )
        parts.append(ddl)
        # Table-level comment.
        if e.get("name_zh"):
            parts.append(
                f"COMMENT ON TABLE {tbl_q} IS "
                f"{_quote_literal(e['name_zh'])};\n"
            )
        for s in post_stmts:
            parts.append(s + "\n")
        parts.append("")  # blank line between tables

    return "\n".join(parts).rstrip() + "\n"
