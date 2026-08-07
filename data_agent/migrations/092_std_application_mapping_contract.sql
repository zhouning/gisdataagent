-- 092: Version-bound standard application mapping contracts.
-- These rows are governance artifacts. They do not publish a DataProductVersion
-- and they never mutate raw/source data.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'std_data_element_id_version_key'
    ) THEN
        ALTER TABLE std_data_element
            ADD CONSTRAINT std_data_element_id_version_key
            UNIQUE (id, document_version_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS std_application_mapping_contract (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_kind             TEXT NOT NULL
                                CHECK (source_kind IN
                                    ('virtual_source','asset','resource_version')),
    source_ref              TEXT NOT NULL,
    source_snapshot_hash    TEXT,
    standard_version_id     UUID NOT NULL
                                REFERENCES std_document_version(id) ON DELETE CASCADE,
    status                  TEXT NOT NULL DEFAULT 'proposed'
                                CHECK (status IN ('proposed','confirmed','superseded')),
    mapping_hash            TEXT NOT NULL,
    created_by              TEXT NOT NULL,
    confirmed_by            TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at            TIMESTAMPTZ,
    superseded_at           TIMESTAMPTZ,
    metadata                JSONB NOT NULL DEFAULT '{}',
    UNIQUE (id, standard_version_id),
    UNIQUE (source_kind, source_ref, mapping_hash),
    CHECK (source_snapshot_hash IS NULL OR length(source_snapshot_hash) = 64),
    CHECK (length(mapping_hash) = 64),
    CHECK ((status <> 'confirmed') OR
           (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_std_application_mapping_one_confirmed
    ON std_application_mapping_contract(source_kind, source_ref)
    WHERE status = 'confirmed';
CREATE INDEX IF NOT EXISTS idx_std_application_mapping_standard
    ON std_application_mapping_contract(standard_version_id, status);

CREATE TABLE IF NOT EXISTS std_application_field_mapping (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id             UUID NOT NULL,
    standard_version_id     UUID NOT NULL,
    source_field            TEXT NOT NULL,
    target_data_element_id  UUID NOT NULL,
    target_field            TEXT NOT NULL,
    confidence              NUMERIC(7,6) NOT NULL DEFAULT 0
                                CHECK (confidence >= 0 AND confidence <= 1),
    match_method            TEXT NOT NULL,
    evidence                JSONB NOT NULL DEFAULT '{}',
    transform_spec          JSONB NOT NULL DEFAULT '{"operation":"rename"}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (contract_id, standard_version_id)
        REFERENCES std_application_mapping_contract(id, standard_version_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_std_application_field_target_version
    FOREIGN KEY (target_data_element_id, standard_version_id)
        REFERENCES std_data_element(id, document_version_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    UNIQUE (contract_id, source_field),
    UNIQUE (contract_id, target_data_element_id),
    CHECK (jsonb_typeof(evidence) = 'object'),
    CHECK (jsonb_typeof(transform_spec) = 'object'),
    CHECK (transform_spec ? 'operation' AND
           transform_spec->>'operation' = 'rename')
);

CREATE INDEX IF NOT EXISTS idx_std_application_field_target
    ON std_application_field_mapping(target_data_element_id);
