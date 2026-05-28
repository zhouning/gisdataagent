-- 082: Wave 6+ — agent_semantic_sources.derived_synonyms column for the
--      to_synonym derivation strategy. Manual `synonyms` column stays
--      authoritative for hand-curated table aliases; the new column carries
--      strategy-derived aliases keyed by std_derived_link bookkeeping.
--
-- Why a sibling column instead of a table:
--   - Manual edits to .synonyms must stay isolated from rerun semantics
--     (rerun WIPES derived_synonyms only, never touches synonyms).
--   - Grounding (semantic_layer.py:_get_cached_sources) merges both lists
--     in one place; no SQL UNION cross-table cost.
--
-- Stale model: when SynonymStrategy reruns, it overwrites derived_synonyms
-- on each touched row to the new value; rows that previously had derived
-- synonyms but no longer do get reset to '[]'. std_derived_link entries
-- track (source_kind=data_element|term, target=agent_semantic_sources.id)
-- and follow the same active/stale/superseded conventions.

ALTER TABLE agent_semantic_sources
    ADD COLUMN IF NOT EXISTS derived_synonyms JSONB NOT NULL
        DEFAULT '[]'::jsonb;

-- Index for grounding cache rebuild (rare, but cheap).
CREATE INDEX IF NOT EXISTS idx_agent_semantic_sources_derived_syn
    ON agent_semantic_sources USING GIN (derived_synonyms);
