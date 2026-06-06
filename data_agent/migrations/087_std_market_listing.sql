-- 087: Standards market listing review workflow.

CREATE TABLE IF NOT EXISTS std_market_listing (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    document_id     UUID NOT NULL REFERENCES std_document(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'submitted',
    submitted_by    TEXT NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_by     TEXT,
    reviewed_at     TIMESTAMPTZ,
    notes           TEXT,
    review_notes    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT std_market_listing_status_check
        CHECK (status IN ('submitted','approved','rejected','withdrawn')),
    CONSTRAINT std_market_listing_version_unique UNIQUE (version_id)
);

CREATE INDEX IF NOT EXISTS idx_std_market_listing_status
    ON std_market_listing(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_std_market_listing_document
    ON std_market_listing(document_id);
