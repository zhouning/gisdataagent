-- Data Classification: add sensitivity fields to data catalog (v15.0)
ALTER TABLE agent_data_catalog ADD COLUMN IF NOT EXISTS sensitivity_level VARCHAR(20) DEFAULT 'public';
ALTER TABLE agent_data_catalog ADD COLUMN IF NOT EXISTS field_classifications JSONB DEFAULT '{}';
