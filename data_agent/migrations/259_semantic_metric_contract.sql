-- Keep governed metric grain, population, aggregation and provenance together.
ALTER TABLE agent_semantic_metrics
    ADD COLUMN semantic_contract JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT semantic_metric_contract_object
        CHECK (jsonb_typeof(semantic_contract) = 'object');

COMMENT ON COLUMN agent_semantic_metrics.semantic_contract IS
    'Governed metric row grain, aggregation, population, NULL policy, dimensions and public provenance.';
