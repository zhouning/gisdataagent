-- 076: extend std_reference to support std_data_element / std_term targets,
--      split inserter from verifier semantics, and add verification_status.

ALTER TABLE std_reference
  ADD COLUMN IF NOT EXISTS target_data_element_id UUID REFERENCES std_data_element(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS target_term_id         UUID REFERENCES std_term(id)         ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS inserted_by            TEXT,
  ADD COLUMN IF NOT EXISTS inserted_at            TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS verification_status    TEXT NOT NULL DEFAULT 'pending';

-- Historical rows: prior to this migration, verified_by/verified_at actually
-- held inserter info. Move those values to the new columns. Currently 0 rows
-- in std_reference, so this is a no-op in practice but kept for safety.
UPDATE std_reference
   SET inserted_by = verified_by,
       inserted_at = verified_at
 WHERE inserted_by IS NULL;

-- Reset verified_* so they are filled by the review stage only (Wave 4).
UPDATE std_reference SET verified_by = NULL, verified_at = NULL;

-- Extend allowed target_kind values
ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_target_kind_check;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_kind_check
  CHECK (target_kind IN (
    'std_clause','std_data_element','std_term','std_document',
    'external_url','web_snapshot','internet_search'));

-- target_kind <-> FK column consistency
ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_target_consistency;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_consistency CHECK (
  (target_kind = 'std_clause'       AND target_clause_id        IS NOT NULL) OR
  (target_kind = 'std_data_element' AND target_data_element_id  IS NOT NULL) OR
  (target_kind = 'std_term'         AND target_term_id          IS NOT NULL) OR
  (target_kind = 'std_document'     AND target_document_id      IS NOT NULL) OR
  (target_kind IN ('external_url','web_snapshot','internet_search')
                                    AND target_url              IS NOT NULL)
);

ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_verification_status_check;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_verification_status_check
  CHECK (verification_status IN ('pending','approved','rejected'));

CREATE INDEX IF NOT EXISTS idx_std_reference_tgt_de              ON std_reference(target_data_element_id);
CREATE INDEX IF NOT EXISTS idx_std_reference_tgt_term            ON std_reference(target_term_id);
CREATE INDEX IF NOT EXISTS idx_std_reference_verification_status ON std_reference(verification_status);

-- v1-fixes follow-up: tighten ON DELETE behavior on all target_*_id FKs.
-- The new target_consistency CHECK constraint is incompatible with SET NULL
-- (deleting a target row would set target_*_id=NULL, violating the CHECK).
-- CASCADE removes the orphaned reference instead, matching the strict
-- consistency intent.
ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_target_clause_id_fkey;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_clause_id_fkey
  FOREIGN KEY (target_clause_id) REFERENCES std_clause(id) ON DELETE CASCADE;

ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_target_document_id_fkey;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_document_id_fkey
  FOREIGN KEY (target_document_id) REFERENCES std_document(id) ON DELETE CASCADE;

ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_target_data_element_id_fkey;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_data_element_id_fkey
  FOREIGN KEY (target_data_element_id) REFERENCES std_data_element(id) ON DELETE CASCADE;

ALTER TABLE std_reference DROP CONSTRAINT IF EXISTS std_reference_target_term_id_fkey;
ALTER TABLE std_reference ADD CONSTRAINT std_reference_target_term_id_fkey
  FOREIGN KEY (target_term_id) REFERENCES std_term(id) ON DELETE CASCADE;
