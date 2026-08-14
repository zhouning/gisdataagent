-- 165: Persist the bounded irrigation planner contract with each model run.
--
-- Migration 163 stored numerical results and the Proposal, but omitted the
-- planner metadata from the durable run row. Existing rows remain immutable;
-- their missing planner metadata is reconstructed by the service on read.

ALTER TABLE gda_control.irrigation_world_model_run
    ADD COLUMN IF NOT EXISTS planner_contract JSONB;

ALTER TABLE gda_control.irrigation_world_model_run
    DROP CONSTRAINT IF EXISTS ck_gda_irrigation_run_planner_contract;
ALTER TABLE gda_control.irrigation_world_model_run
    ADD CONSTRAINT ck_gda_irrigation_run_planner_contract
    CHECK (
        planner_contract IS NULL
        OR jsonb_typeof(planner_contract) = 'object'
    );

COMMENT ON COLUMN gda_control.irrigation_world_model_run.planner_contract IS
    'Bounded candidate ranking evidence; NULL only for runs created before migration 165.';
