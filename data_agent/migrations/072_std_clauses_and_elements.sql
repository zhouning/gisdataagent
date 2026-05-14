-- Migration 072: clause tree + data elements + value domains + terms.
-- Embedding dimension is pinned to 768 (embedding_gateway default).

CREATE TABLE IF NOT EXISTS std_clause (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id             UUID NOT NULL REFERENCES std_document(id) ON DELETE CASCADE,
    document_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    parent_clause_id        UUID REFERENCES std_clause(id) ON DELETE CASCADE,
    ordinal_path            LTREE NOT NULL,
    heading                 TEXT,
    clause_no               TEXT,
    kind                    TEXT NOT NULL
                                CHECK (kind IN ('chapter','section','clause','paragraph',
                                    'definition','requirement','example','note','figure','table')),
    body_md                 TEXT DEFAULT '',
    body_html               TEXT,
    checksum                TEXT,
    lock_holder             TEXT,
    lock_expires_at         TIMESTAMPTZ,
    source_origin           JSONB,
    embedding               VECTOR(768),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by              TEXT,
    updated_by              TEXT,
    UNIQUE (document_version_id, ordinal_path)
);
CREATE INDEX IF NOT EXISTS idx_std_clause_path ON std_clause USING GIST (ordinal_path);
CREATE INDEX IF NOT EXISTS idx_std_clause_parent ON std_clause(parent_clause_id);
CREATE INDEX IF NOT EXISTS idx_std_clause_docver ON std_clause(document_version_id);

CREATE TABLE IF NOT EXISTS std_term (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    term_code               TEXT NOT NULL,
    name_zh                 TEXT NOT NULL,
    name_en                 TEXT,
    definition              TEXT,
    aliases                 TEXT[] DEFAULT '{}',
    defined_by_clause_id    UUID REFERENCES std_clause(id) ON DELETE SET NULL,
    embedding               VECTOR(768),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, term_code)
);

CREATE TABLE IF NOT EXISTS std_value_domain (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    code                    TEXT NOT NULL,
    name                    TEXT NOT NULL,
    kind                    TEXT NOT NULL
                                CHECK (kind IN ('enumeration','range','pattern','external_codelist')),
    defined_by_clause_id    UUID REFERENCES std_clause(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, code)
);

CREATE TABLE IF NOT EXISTS std_value_domain_item (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    value_domain_id         UUID NOT NULL REFERENCES std_value_domain(id) ON DELETE CASCADE,
    value                   TEXT NOT NULL,
    label_zh                TEXT,
    label_en                TEXT,
    ordinal                 INT NOT NULL DEFAULT 0,
    UNIQUE (value_domain_id, value),
    UNIQUE (value_domain_id, ordinal)
);

CREATE TABLE IF NOT EXISTS std_data_element (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_version_id     UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    code                    TEXT NOT NULL,
    name_zh                 TEXT NOT NULL,
    name_en                 TEXT,
    definition              TEXT,
    representation_class    TEXT
                                CHECK (representation_class IN
                                    ('code','text','integer','decimal','datetime','geometry','boolean')),
    datatype                TEXT,
    unit                    TEXT,
    value_domain_id         UUID REFERENCES std_value_domain(id) ON DELETE SET NULL,
    obligation              TEXT NOT NULL DEFAULT 'optional'
                                CHECK (obligation IN ('mandatory','conditional','optional')),
    cardinality             TEXT DEFAULT '1',
    defined_by_clause_id    UUID REFERENCES std_clause(id) ON DELETE SET NULL,
    term_id                 UUID REFERENCES std_term(id) ON DELETE SET NULL,
    data_classification     TEXT,
    embedding               VECTOR(768),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, code)
);
CREATE INDEX IF NOT EXISTS idx_std_data_element_docver ON std_data_element(document_version_id);
