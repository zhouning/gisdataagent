-- 081: Wave 6 — extend agent_semantic_hints.hint_kind enumeration so
--      ValueDomainStrategy can emit kind-specific rows for std_value_domain
--      kinds (range / pattern / external_codelist). enumeration kind keeps
--      reusing existing 'value_enum' row.
--
-- Why three new kinds instead of overloading existing ones:
--   - 'value_range'    — numeric/date min/max bounds (decimal field range)
--   - 'value_pattern'  — regex / format constraint (e.g. dlbm 4-digit code)
--   - 'value_codelist' — external code list reference (GB/T 21010 etc.)
-- Grounding does not branch on hint_kind (semantic_layer.py just reads
-- hint_text_zh + severity), so no consumer-side change is needed.

ALTER TABLE agent_semantic_hints
    DROP CONSTRAINT IF EXISTS agent_semantic_hints_hint_kind_check;

ALTER TABLE agent_semantic_hints
    ADD CONSTRAINT agent_semantic_hints_hint_kind_check
        CHECK (hint_kind IN (
            'filter_default', 'value_enum', 'join_note',
            'unit_note', 'exclusion', 'category_choice',
            'quoting', 'size_class', 'srid_note', 'other',
            'value_range', 'value_pattern', 'value_codelist'
        ));
