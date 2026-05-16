-- 077: relax target_consistency CHECK so internet_search rows may have
--      NULL target_url. KB-chunk citations are mapped to internet_search
--      and have no URL by definition; the previous CHECK rejected them.

ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_target_consistency;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_consistency CHECK (
  (target_kind = 'std_clause'       AND target_clause_id        IS NOT NULL) OR
  (target_kind = 'std_data_element' AND target_data_element_id  IS NOT NULL) OR
  (target_kind = 'std_term'         AND target_term_id          IS NOT NULL) OR
  (target_kind = 'std_document'     AND target_document_id      IS NOT NULL) OR
  (target_kind IN ('external_url','web_snapshot') AND target_url IS NOT NULL) OR
  (target_kind = 'internet_search')
);
