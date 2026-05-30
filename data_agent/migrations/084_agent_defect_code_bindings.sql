-- 084: Wave 7 — agent_defect_code_bindings: bind std_data_element to a
--      defect_code (drawn from defect_taxonomy.yaml). Multi-binding allowed
--      because one element can violate multiple defect categories
--      (e.g. a mandatory field with a value_domain triggers both
--       MIS-001 missing-required and NRM-003 value-out-of-range).
--
-- Why a binding table rather than a column on agent_quality_rules:
--   defect_code is independent of rule_type. A `completeness` rule may map
--   to MIS-001, a `field_check` rule to NRM-002 or NRM-003, and the QC
--   report engine needs to surface defects independently of how they were
--   detected. Keeping the binding separate also lets us layer a future
--   "manual defect annotation" surface on the same key without bothering
--   the rule engine.
--
-- The table is purely standards-platform owned. Defect codes live in YAML
-- (no FK target inside the DB); we store the code as TEXT and validate
-- against DefectTaxonomy at the application layer.

CREATE TABLE IF NOT EXISTS agent_defect_code_bindings (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    std_data_element_id  UUID NOT NULL REFERENCES std_data_element(id) ON DELETE CASCADE,
    defect_code          TEXT NOT NULL,
    severity             TEXT NOT NULL CHECK (severity IN ('A','B','C')),
    category             TEXT NOT NULL,
    binding_kind         TEXT NOT NULL
                              CHECK (binding_kind IN (
                                  'mandatory','enumeration','range','pattern',
                                  'manual')),
    notes                TEXT,
    std_derived_link_id  UUID REFERENCES std_derived_link(id) ON DELETE SET NULL,
    std_version_id       UUID,
    source_tag           TEXT,
    derived_status       TEXT
                              CHECK (derived_status IS NULL OR derived_status IN ('active','stale')),
    owner_username       TEXT NOT NULL DEFAULT 'system',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Uniqueness: same (element, defect_code, binding_kind) only once.
    -- Different binding_kinds for the same code/element are allowed because
    -- a future manual override may co-exist with a derived row.
    UNIQUE (std_data_element_id, defect_code, binding_kind)
);

CREATE INDEX IF NOT EXISTS idx_defect_bindings_element
    ON agent_defect_code_bindings(std_data_element_id);
CREATE INDEX IF NOT EXISTS idx_defect_bindings_code
    ON agent_defect_code_bindings(defect_code);
CREATE INDEX IF NOT EXISTS idx_defect_bindings_link
    ON agent_defect_code_bindings(std_derived_link_id)
    WHERE std_derived_link_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_defect_bindings_derived
    ON agent_defect_code_bindings(std_version_id, derived_status)
    WHERE std_derived_link_id IS NOT NULL;
