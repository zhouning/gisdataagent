CREATE TABLE IF NOT EXISTS std_outbox (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type        TEXT NOT NULL
                          CHECK (event_type IN (
                              'extract_requested','structure_requested',
                              'embed_requested','dedupe_requested',
                              'web_snapshot_requested','version_released',
                              'clause_updated','derivation_requested',
                              'invalidation_needed')),
    payload           JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at      TIMESTAMPTZ,
    attempts          INT NOT NULL DEFAULT 0,
    last_error        TEXT,
    next_attempt_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status            TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','in_flight','done','failed'))
);

CREATE INDEX IF NOT EXISTS idx_std_outbox_pending
    ON std_outbox(next_attempt_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_std_outbox_status ON std_outbox(status);
