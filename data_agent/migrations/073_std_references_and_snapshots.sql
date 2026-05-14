CREATE TABLE IF NOT EXISTS std_web_snapshot (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    url             TEXT NOT NULL,
    http_status     INT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    html_path       TEXT,
    pdf_path        TEXT,
    extracted_text  TEXT,
    search_query    TEXT
);
CREATE INDEX IF NOT EXISTS idx_std_web_snapshot_url ON std_web_snapshot(url);

CREATE TABLE IF NOT EXISTS std_reference (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_clause_id         UUID REFERENCES std_clause(id) ON DELETE CASCADE,
    source_data_element_id   UUID REFERENCES std_data_element(id) ON DELETE CASCADE,
    target_kind              TEXT NOT NULL
                                 CHECK (target_kind IN (
                                     'std_clause','std_document',
                                     'external_url','web_snapshot','internet_search')),
    target_clause_id         UUID REFERENCES std_clause(id) ON DELETE SET NULL,
    target_document_id       UUID REFERENCES std_document(id) ON DELETE SET NULL,
    target_url               TEXT,
    target_doi               TEXT,
    snapshot_id              UUID REFERENCES std_web_snapshot(id) ON DELETE SET NULL,
    citation_text            TEXT NOT NULL,
    confidence               NUMERIC(3,2),
    verified_by              TEXT,
    verified_at              TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_clause_id IS NOT NULL OR source_data_element_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_std_reference_src_clause ON std_reference(source_clause_id);
CREATE INDEX IF NOT EXISTS idx_std_reference_src_de ON std_reference(source_data_element_id);

CREATE TABLE IF NOT EXISTS std_search_session (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_version_id  UUID REFERENCES std_document_version(id) ON DELETE CASCADE,
    clause_id            UUID REFERENCES std_clause(id) ON DELETE CASCADE,
    author_user_id       TEXT NOT NULL,
    messages             JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS std_search_hit (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id   UUID NOT NULL REFERENCES std_search_session(id) ON DELETE CASCADE,
    query        TEXT NOT NULL,
    rank         INT NOT NULL,
    snapshot_id  UUID REFERENCES std_web_snapshot(id) ON DELETE SET NULL,
    snippet      TEXT
);
