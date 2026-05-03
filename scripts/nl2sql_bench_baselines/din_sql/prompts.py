"""DIN-SQL prompts adapted for PostgreSQL/PostGIS.

Based on the DIN-SQL paper (Pourreza & Rafiei, 2023) prompt structure,
adapted from SQLite to PostgreSQL dialect with PostGIS extensions.
"""

SCHEMA_LINKING_PROMPT = '''Given the database schema and a question, identify the relevant tables and columns.

Schema:
{schema}

Question: {question}
Evidence: {evidence}

List the relevant tables and columns in this format:
Tables: table1, table2, ...
Columns: table1.col1, table1.col2, table2.col3, ...
Foreign keys: table1.col = table2.col, ...
'''

CLASSIFICATION_PROMPT = '''Given a question and its linked schema elements, classify the SQL query difficulty.

Question: {question}
Evidence: {evidence}
Schema links: {schema_links}

Classify as one of:
- EASY: single table, simple filter/aggregation
- MEDIUM: 2-3 tables with joins, moderate aggregation
- HARD: 4+ tables, subqueries, complex aggregation, set operations

Output only the classification label (EASY, MEDIUM, or HARD).
'''

SQL_GENERATION_EASY = '''Generate a PostgreSQL SELECT query for this question.

Database dialect: PostgreSQL with PostGIS extension.
Schema:
{schema}

Question: {question}
Evidence: {evidence}
Relevant tables and columns: {schema_links}

Rules:
- Output ONLY the SQL query, no explanation.
- Use PostgreSQL syntax (not SQLite/MySQL).
- Double-quote column names that contain uppercase letters.
- For geometry columns, use PostGIS functions (ST_Area, ST_Length, ST_Intersects, etc.).
- Cast to ::geography for real-world distance/area calculations.
- ROUND requires ::numeric cast: ROUND(expr::numeric, N).
- Only generate SELECT queries.

SQL:
'''

SQL_GENERATION_MEDIUM = '''Generate a PostgreSQL SELECT query for this question. The query likely requires joins between multiple tables.

Database dialect: PostgreSQL with PostGIS extension.
Schema:
{schema}

Question: {question}
Evidence: {evidence}
Relevant tables and columns: {schema_links}

Rules:
- Output ONLY the SQL query, no explanation.
- Use PostgreSQL syntax (not SQLite/MySQL).
- Double-quote column names that contain uppercase letters.
- Use explicit JOIN syntax (not implicit comma joins).
- For geometry columns, use PostGIS functions.
- Cast to ::geography for real-world distance/area calculations.
- ROUND requires ::numeric cast.
- Only generate SELECT queries.

SQL:
'''

SQL_GENERATION_HARD = '''Generate a PostgreSQL SELECT query for this complex question. The query may require subqueries, CTEs, set operations, or complex aggregation.

Database dialect: PostgreSQL with PostGIS extension.
Schema:
{schema}

Question: {question}
Evidence: {evidence}
Relevant tables and columns: {schema_links}

Rules:
- Output ONLY the SQL query, no explanation.
- Use PostgreSQL syntax (not SQLite/MySQL).
- Double-quote column names that contain uppercase letters.
- Prefer CTEs (WITH clauses) over deeply nested subqueries.
- Use explicit JOIN syntax.
- For geometry columns, use PostGIS functions.
- Cast to ::geography for real-world distance/area calculations.
- ROUND requires ::numeric cast.
- Only generate SELECT queries.

SQL:
'''

SELF_CORRECTION_PROMPT = '''The following SQL query failed with an error. Fix it.

Database dialect: PostgreSQL with PostGIS extension.
Schema:
{schema}

Original question: {question}
Failed SQL: {failed_sql}
Error: {error}

Rules:
- Output ONLY the fixed SQL query, no explanation.
- Use PostgreSQL syntax.
- Double-quote uppercase column names.
- ROUND requires ::numeric cast.
- Only generate SELECT queries.

Fixed SQL:
'''

DIFFICULTY_TO_PROMPT = {
    "EASY": SQL_GENERATION_EASY,
    "MEDIUM": SQL_GENERATION_MEDIUM,
    "HARD": SQL_GENERATION_HARD,
}
