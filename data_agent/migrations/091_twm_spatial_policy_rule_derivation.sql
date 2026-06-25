-- 091: TWM Phase 6 — allow standards-platform derivation links to point at
--      generated TWM spatial policy-rule candidates.
--
-- This is a strict superset of migration 085's target_kind constraint. The
-- new to_spatial_policy_rule strategy writes:
--   target_kind  = 'spatial_policy_rule'
--   target_table = 'twm_policy_rule'

ALTER TABLE std_derived_link
    DROP CONSTRAINT IF EXISTS std_derived_link_target_kind_check;

ALTER TABLE std_derived_link
    ADD CONSTRAINT std_derived_link_target_kind_check
        CHECK (target_kind IN (
            'semantic_hint','value_semantic','synonym',
            'qc_rule','defect_code','data_model_attribute',
            'table_column',
            'data_model',
            'spatial_policy_rule'
        ));
