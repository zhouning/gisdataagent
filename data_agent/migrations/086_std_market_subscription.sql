-- 086: Standards market user subscriptions.

CREATE TABLE IF NOT EXISTS std_market_subscription (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscriber_user_id      TEXT NOT NULL,
    document_id             UUID NOT NULL REFERENCES std_document(id) ON DELETE CASCADE,
    source_version_id       UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    last_seen_version_id    UUID REFERENCES std_document_version(id) ON DELETE SET NULL,
    status                  TEXT NOT NULL DEFAULT 'active',
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT std_market_subscription_status_check
        CHECK (status IN ('active','cancelled')),
    CONSTRAINT std_market_subscription_user_doc_unique
        UNIQUE (subscriber_user_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_std_market_subscription_user_status
    ON std_market_subscription(subscriber_user_id, status);

CREATE INDEX IF NOT EXISTS idx_std_market_subscription_document
    ON std_market_subscription(document_id);
