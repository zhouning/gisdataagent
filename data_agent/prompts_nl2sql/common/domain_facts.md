# Common domain facts (family-invariant)

These facts are PostGIS / PostgreSQL truths and apply to every LLM family. Each
per-family `system_instruction.md` references them via inclusion or restating
in family-appropriate phrasing.

## Geometry / measurement
- Real-world area uses geography cast: `ST_Area(geometry::geography)` returns
  square metres. Bare `ST_Area(geometry)` without the cast returns square
  degrees on geographic (unprojected) SRIDs and is ALWAYS a bug.
- Real-world length: `ST_Length(geometry::geography)` returns metres.
- Distance threshold filtering: `ST_DWithin(a::geography, b::geography, metres)`.
- Dataset-specific column caveats (e.g. "SHAPE_Area is stored in degrees²"
  or "TBMJ is pre-computed real m²") are injected at runtime under
  `## Business rules` — follow those in preference to any generic assumption.

## Spatial predicates
- Intersection (geometries share any point): `ST_Intersects(a, b)`.
- Containment (b is fully inside a): `ST_Contains(a, b)`.
- Within (a is fully inside b): `ST_Within(a, b)`.
- These three are NOT interchangeable — pick the one matching the question's
  vocabulary. Do not substitute `ST_DWithin(..., 0.00005)` for `ST_Intersects`.

## KNN ranking
- Nearest-neighbour ranking uses the PostGIS KNN index operator:
  `ORDER BY a.geometry <-> b.geometry LIMIT K`.
- Do NOT use `ORDER BY ST_Distance(...)` as the ranking clause — that disables
  the index and produces wrong row order on large tables.
- `ST_Distance` belongs in the SELECT list (to report the value), not in the
  ORDER BY ranking position.

## Numeric formatting
- `ROUND(expr, N)` requires `numeric` type in PostgreSQL: `ROUND(expr::numeric, N)`.
- Do NOT wrap raw aggregate results (AVG, SUM, MAX, MIN) in ROUND or COALESCE
  unless the question explicitly asks for a specific number of decimal places
  or a default-when-null behaviour.

## Identifier quoting
- Any column whose name contains uppercase letters or non-ASCII characters
  must be double-quoted. The PostgreSQL parser folds unquoted identifiers to
  lowercase, so uppercase columns without quotes will fail with "column does
  not exist".

## Read-only safety
- Generate only SELECT (or WITH ... SELECT) statements.
- Never generate DELETE, UPDATE, DROP, INSERT, ALTER, TRUNCATE.
- If asked to modify data, return `SELECT 1` as a refusal placeholder
  (distinct from a give-up — see family-specific rules for the boundary).

## Bounded-output policy
- The current dataset's large-tables list is injected at runtime under
  `## Large tables` in the grounding context.
- When the question asks for unbounded listing on those tables (keywords:
  "全部 / 所有 / 整张表 / 列出所有 / 显示全部 / all / every"), apply
  `LIMIT 1000` and include a SQL comment `/* auto-limited 1000 */`.
- An empty WHERE on a large table is also an unbounded-output request — apply
  the same LIMIT 1000 rule.
- This is a bounded-output policy, NOT a refusal. Do not return empty.
