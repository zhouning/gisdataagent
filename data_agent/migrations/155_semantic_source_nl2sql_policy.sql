-- Governed NL2Semantic2SQL source selection.
-- Multiple physical tables may describe the same business object (for
-- example current, historical and staging DLTB versions).  The semantic
-- layer must state which ones may participate in NL2SQL and their precedence.

ALTER TABLE agent_semantic_sources
    ADD COLUMN IF NOT EXISTS nl2sql_enabled BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE agent_semantic_sources
    ADD COLUMN IF NOT EXISTS nl2sql_priority INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_semantic_sources
    DROP CONSTRAINT IF EXISTS ck_semantic_sources_nl2sql_priority;

ALTER TABLE agent_semantic_sources
    ADD CONSTRAINT ck_semantic_sources_nl2sql_priority
    CHECK (nl2sql_priority BETWEEN -1000 AND 1000);

CREATE INDEX IF NOT EXISTS idx_semantic_sources_nl2sql_selection
    ON agent_semantic_sources (nl2sql_enabled, nl2sql_priority DESC, table_name);
