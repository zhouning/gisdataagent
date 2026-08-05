-- 117: Versioned natural-resource ontology authority and immutable packages.

CREATE SCHEMA IF NOT EXISTS gda_ontology;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS gda_ontology.ontology_version (
    ontology_version_id UUID PRIMARY KEY,
    ontology_key TEXT NOT NULL,
    semantic_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    parent_version_id UUID REFERENCES gda_ontology.ontology_version(ontology_version_id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    namespace_uri TEXT NOT NULL,
    source_fingerprint CHAR(64) NOT NULL,
    content_sha256 CHAR(64),
    model_profile TEXT NOT NULL DEFAULT 'owl2-rl-bounded',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_by TEXT,
    published_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_ontology_version UNIQUE (ontology_key, semantic_version),
    CONSTRAINT ck_gda_ontology_version_status CHECK (
        status IN ('draft', 'validated', 'published', 'retired', 'rejected')
    ),
    CONSTRAINT ck_gda_ontology_version_semver CHECK (
        semantic_version ~ '^[0-9]+\.[0-9]+\.[0-9]+([+-][A-Za-z0-9.-]+)?$'
    ),
    CONSTRAINT ck_gda_ontology_version_source_hash CHECK (
        source_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_ontology_version_content_hash CHECK (
        content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_ontology_version_publish_state CHECK (
        (status IN ('published', 'retired') AND content_sha256 IS NOT NULL
            AND published_by IS NOT NULL AND published_at IS NOT NULL)
        OR status NOT IN ('published', 'retired')
    )
);

CREATE TABLE IF NOT EXISTS gda_ontology.ontology_source (
    ontology_version_id UUID NOT NULL REFERENCES gda_ontology.ontology_version(ontology_version_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    title TEXT NOT NULL,
    locator TEXT NOT NULL,
    source_version TEXT,
    sha256 CHAR(64) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (ontology_version_id, source_id),
    CONSTRAINT ck_gda_ontology_source_kind CHECK (
        source_kind IN ('ea_repository', 'standard_document', 'controlled_vocabulary', 'manual_governance')
    ),
    CONSTRAINT ck_gda_ontology_source_hash CHECK (sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS gda_ontology.concept (
    ontology_version_id UUID NOT NULL REFERENCES gda_ontology.ontology_version(ontology_version_id) ON DELETE CASCADE,
    concept_id TEXT NOT NULL,
    uri TEXT NOT NULL,
    kind TEXT NOT NULL,
    code TEXT,
    pref_label TEXT NOT NULL,
    alt_labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    definition TEXT NOT NULL DEFAULT '',
    domain_id TEXT,
    source_system TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_object_id TEXT,
    ea_guid TEXT,
    package_path TEXT,
    geometry_type TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    search_document TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(code, '') || ' ' || pref_label || ' ' ||
            coalesce(alt_labels::text, '') || ' ' || coalesce(definition, ''))
    ) STORED,
    PRIMARY KEY (ontology_version_id, concept_id),
    UNIQUE (ontology_version_id, uri),
    FOREIGN KEY (ontology_version_id, source_id)
        REFERENCES gda_ontology.ontology_source(ontology_version_id, source_id),
    CONSTRAINT ck_gda_ontology_concept_status CHECK (
        lifecycle_status IN ('candidate', 'active', 'deprecated', 'rejected')
    ),
    CONSTRAINT ck_gda_ontology_concept_uri_size CHECK (octet_length(uri) <= 2000)
);

CREATE INDEX IF NOT EXISTS idx_gda_ontology_concept_search
    ON gda_ontology.concept USING GIN (search_document);
CREATE INDEX IF NOT EXISTS idx_gda_ontology_concept_label_trgm
    ON gda_ontology.concept USING GIN (pref_label gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_gda_ontology_concept_code
    ON gda_ontology.concept (ontology_version_id, lower(code));
CREATE INDEX IF NOT EXISTS idx_gda_ontology_concept_domain_kind
    ON gda_ontology.concept (ontology_version_id, domain_id, kind);

CREATE TABLE IF NOT EXISTS gda_ontology.property (
    ontology_version_id UUID NOT NULL,
    property_id TEXT NOT NULL,
    owner_concept_id TEXT NOT NULL,
    uri TEXT NOT NULL,
    code TEXT NOT NULL,
    pref_label TEXT NOT NULL,
    datatype TEXT,
    length INTEGER,
    precision_value INTEGER,
    scale_value INTEGER,
    min_count INTEGER NOT NULL DEFAULT 0,
    max_count INTEGER DEFAULT 1,
    ordinal INTEGER NOT NULL DEFAULT 0,
    value_domain JSONB,
    default_value TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    source_id TEXT NOT NULL,
    source_object_id TEXT,
    ea_guid TEXT,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (ontology_version_id, property_id),
    UNIQUE (ontology_version_id, uri),
    FOREIGN KEY (ontology_version_id, owner_concept_id)
        REFERENCES gda_ontology.concept(ontology_version_id, concept_id) ON DELETE CASCADE,
    FOREIGN KEY (ontology_version_id, source_id)
        REFERENCES gda_ontology.ontology_source(ontology_version_id, source_id),
    CONSTRAINT ck_gda_ontology_property_cardinality CHECK (
        min_count >= 0 AND (max_count IS NULL OR max_count >= min_count)
    ),
    CONSTRAINT ck_gda_ontology_property_status CHECK (
        lifecycle_status IN ('candidate', 'active', 'deprecated', 'rejected')
    ),
    CONSTRAINT ck_gda_ontology_property_uri_size CHECK (octet_length(uri) <= 2000)
);

CREATE INDEX IF NOT EXISTS idx_gda_ontology_property_owner
    ON gda_ontology.property (ontology_version_id, owner_concept_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_gda_ontology_property_code
    ON gda_ontology.property (ontology_version_id, lower(code));

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_gda_ontology_concept_uri_size'
          AND conrelid = 'gda_ontology.concept'::regclass
    ) THEN
        ALTER TABLE gda_ontology.concept
            ADD CONSTRAINT ck_gda_ontology_concept_uri_size
            CHECK (octet_length(uri) <= 2000);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_gda_ontology_property_uri_size'
          AND conrelid = 'gda_ontology.property'::regclass
    ) THEN
        ALTER TABLE gda_ontology.property
            ADD CONSTRAINT ck_gda_ontology_property_uri_size
            CHECK (octet_length(uri) <= 2000);
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS gda_ontology.relation (
    ontology_version_id UUID NOT NULL,
    relation_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    source_concept_id TEXT NOT NULL,
    target_concept_id TEXT NOT NULL,
    pref_label TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'directed',
    is_transitive BOOLEAN NOT NULL DEFAULT false,
    is_symmetric BOOLEAN NOT NULL DEFAULT false,
    source_id TEXT NOT NULL,
    source_object_id TEXT,
    ea_guid TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (ontology_version_id, relation_id),
    FOREIGN KEY (ontology_version_id, source_concept_id)
        REFERENCES gda_ontology.concept(ontology_version_id, concept_id) ON DELETE CASCADE,
    FOREIGN KEY (ontology_version_id, target_concept_id)
        REFERENCES gda_ontology.concept(ontology_version_id, concept_id) ON DELETE CASCADE,
    FOREIGN KEY (ontology_version_id, source_id)
        REFERENCES gda_ontology.ontology_source(ontology_version_id, source_id),
    CONSTRAINT ck_gda_ontology_relation_direction CHECK (
        direction IN ('directed', 'bidirectional')
    ),
    CONSTRAINT ck_gda_ontology_relation_status CHECK (
        lifecycle_status IN ('candidate', 'active', 'deprecated', 'rejected')
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_ontology_relation_source
    ON gda_ontology.relation (ontology_version_id, source_concept_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_gda_ontology_relation_target
    ON gda_ontology.relation (ontology_version_id, target_concept_id, relation_type);

CREATE TABLE IF NOT EXISTS gda_ontology.mapping (
    ontology_version_id UUID NOT NULL,
    mapping_id TEXT NOT NULL,
    source_concept_id TEXT NOT NULL,
    target_concept_id TEXT NOT NULL,
    mapping_type TEXT NOT NULL,
    mapping_status TEXT NOT NULL,
    confidence NUMERIC(6,5),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    PRIMARY KEY (ontology_version_id, mapping_id),
    FOREIGN KEY (ontology_version_id, source_concept_id)
        REFERENCES gda_ontology.concept(ontology_version_id, concept_id) ON DELETE CASCADE,
    FOREIGN KEY (ontology_version_id, target_concept_id)
        REFERENCES gda_ontology.concept(ontology_version_id, concept_id) ON DELETE CASCADE,
    CONSTRAINT ck_gda_ontology_mapping_type CHECK (
        mapping_type IN ('exact_match', 'close_match', 'broad_match', 'narrow_match', 'related_match')
    ),
    CONSTRAINT ck_gda_ontology_mapping_status CHECK (
        mapping_status IN ('candidate', 'confirmed', 'conflict', 'rejected')
    ),
    CONSTRAINT ck_gda_ontology_mapping_confidence CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    CONSTRAINT ck_gda_ontology_mapping_review CHECK (
        (mapping_status = 'confirmed' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
        OR mapping_status <> 'confirmed'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_ontology_mapping_source
    ON gda_ontology.mapping (ontology_version_id, source_concept_id, mapping_status);
CREATE INDEX IF NOT EXISTS idx_gda_ontology_mapping_target
    ON gda_ontology.mapping (ontology_version_id, target_concept_id, mapping_status);

CREATE TABLE IF NOT EXISTS gda_ontology.validation_result (
    ontology_version_id UUID NOT NULL REFERENCES gda_ontology.ontology_version(ontology_version_id) ON DELETE CASCADE,
    validator_id TEXT NOT NULL,
    validation_kind TEXT NOT NULL,
    conforms BOOLEAN NOT NULL,
    severity TEXT NOT NULL,
    issue_count INTEGER NOT NULL DEFAULT 0,
    report JSONB NOT NULL DEFAULT '{}'::jsonb,
    report_sha256 CHAR(64) NOT NULL,
    validated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ontology_version_id, validator_id),
    CONSTRAINT ck_gda_ontology_validation_severity CHECK (
        severity IN ('info', 'warning', 'error')
    ),
    CONSTRAINT ck_gda_ontology_validation_count CHECK (issue_count >= 0),
    CONSTRAINT ck_gda_ontology_validation_hash CHECK (report_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS gda_ontology.ontology_package (
    ontology_version_id UUID PRIMARY KEY REFERENCES gda_ontology.ontology_version(ontology_version_id),
    package_id TEXT NOT NULL UNIQUE,
    package_format TEXT NOT NULL DEFAULT 'gda-ontology-package-v1',
    package_uri TEXT NOT NULL,
    package_sha256 CHAR(64) NOT NULL,
    rdf_sha256 CHAR(64) NOT NULL,
    shacl_sha256 CHAR(64) NOT NULL,
    jsonld_context_sha256 CHAR(64) NOT NULL,
    signature JSONB,
    projection_status TEXT NOT NULL DEFAULT 'pending',
    projection_checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_gda_ontology_package_hashes CHECK (
        package_sha256 ~ '^[0-9a-f]{64}$'
        AND rdf_sha256 ~ '^[0-9a-f]{64}$'
        AND shacl_sha256 ~ '^[0-9a-f]{64}$'
        AND jsonld_context_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_ontology_projection_status CHECK (
        projection_status IN ('pending', 'building', 'ready', 'failed', 'stale')
    )
);

CREATE TABLE IF NOT EXISTS gda_ontology.active_package (
    ontology_key TEXT PRIMARY KEY,
    ontology_version_id UUID NOT NULL UNIQUE
        REFERENCES gda_ontology.ontology_version(ontology_version_id),
    package_id TEXT NOT NULL REFERENCES gda_ontology.ontology_package(package_id),
    activated_by TEXT NOT NULL,
    activated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION gda_ontology.reject_published_content_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    version_status TEXT;
    target_version UUID;
BEGIN
    target_version := COALESCE(OLD.ontology_version_id, NEW.ontology_version_id);
    SELECT status INTO version_status
      FROM gda_ontology.ontology_version
     WHERE ontology_version_id = target_version;
    IF version_status IN ('published', 'retired') THEN
        RAISE EXCEPTION 'published ontology content is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'ontology_source', 'concept', 'property', 'relation', 'mapping',
        'validation_result'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS reject_published_mutation ON gda_ontology.%I', relation_name);
        EXECUTE format(
            'CREATE TRIGGER reject_published_mutation BEFORE UPDATE OR DELETE ON gda_ontology.%I '
            'FOR EACH ROW EXECUTE FUNCTION gda_ontology.reject_published_content_mutation()',
            relation_name
        );
    END LOOP;
END;
$$;

DO $$
DECLARE
    runtime_role TEXT := current_setting('gda.runtime_role', true);
BEGIN
    IF runtime_role IS NULL OR runtime_role = '' THEN
        runtime_role := 'agent_user';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = runtime_role) THEN
        EXECUTE format('GRANT USAGE ON SCHEMA gda_ontology TO %I', runtime_role);
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA gda_ontology TO %I', runtime_role);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA gda_ontology GRANT SELECT ON TABLES TO %I', runtime_role);
    END IF;
END;
$$;

DO $$
DECLARE
    publisher_role TEXT := current_setting('gda.ontology_publisher_role', true);
BEGIN
    IF publisher_role IS NULL OR publisher_role = '' THEN
        publisher_role := 'gda_ontology_publisher';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = publisher_role) THEN
        EXECUTE format('GRANT USAGE ON SCHEMA gda_ontology TO %I', publisher_role);
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA gda_ontology TO %I',
            publisher_role
        );
        EXECUTE format(
            'ALTER DEFAULT PRIVILEGES IN SCHEMA gda_ontology '
            'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
            publisher_role
        );
    END IF;
END;
$$;
