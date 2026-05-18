-- 078: review_round + review_comment for the review stage
--      (parent spec §4.2.6).

CREATE TABLE IF NOT EXISTS std_review_round (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id  UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
    reviewer_user_id     TEXT NOT NULL,
    initiated_by         TEXT NOT NULL,
    initiated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at            TIMESTAMPTZ NULL,
    status               TEXT NOT NULL DEFAULT 'open',
    outcome              TEXT NULL,
    CONSTRAINT std_review_round_status_check
        CHECK (status IN ('open','closed')),
    CONSTRAINT std_review_round_outcome_check
        CHECK ((status = 'open' AND outcome IS NULL)
            OR (status = 'closed' AND outcome IS NOT NULL
                AND outcome IN ('approved','rejected'))),
    CONSTRAINT std_review_round_closed_at_check
        CHECK ((status = 'open' AND closed_at IS NULL)
            OR (status = 'closed' AND closed_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_std_review_round_one_open_per_version
    ON std_review_round(document_version_id) WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_std_review_round_reviewer
    ON std_review_round(reviewer_user_id, status);

-- Tighten outcome check: PostgreSQL CHECK treats NULL IN (...) as UNKNOWN
-- (which evaluates as true for the constraint), so closed rows with NULL
-- outcome can slip through. Add explicit NOT NULL guard.
ALTER TABLE std_review_round
    DROP CONSTRAINT IF EXISTS std_review_round_outcome_check;
ALTER TABLE std_review_round
    ADD CONSTRAINT std_review_round_outcome_check
        CHECK ((status = 'open' AND outcome IS NULL)
            OR (status = 'closed' AND outcome IS NOT NULL
                AND outcome IN ('approved','rejected')));

CREATE TABLE IF NOT EXISTS std_review_comment (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id            UUID NOT NULL REFERENCES std_review_round(id) ON DELETE CASCADE,
    clause_id           UUID NOT NULL REFERENCES std_clause(id) ON DELETE CASCADE,
    parent_comment_id   UUID NULL REFERENCES std_review_comment(id) ON DELETE CASCADE,
    author_user_id      TEXT NOT NULL,
    body_md             TEXT NOT NULL,
    resolution          TEXT NOT NULL DEFAULT 'open',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ NULL,
    resolved_by         TEXT NULL,
    CONSTRAINT std_review_comment_resolution_check
        CHECK (resolution IN ('open','accepted','rejected','duplicate')),
    CONSTRAINT std_review_comment_body_nonempty_check
        CHECK (length(btrim(body_md)) > 0),
    CONSTRAINT std_review_comment_resolved_consistency_check
        CHECK ((resolution = 'open' AND resolved_at IS NULL AND resolved_by IS NULL)
            OR (resolution != 'open' AND resolved_at IS NOT NULL AND resolved_by IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_std_review_comment_round_clause
    ON std_review_comment(round_id, clause_id);

CREATE INDEX IF NOT EXISTS idx_std_review_comment_open
    ON std_review_comment(round_id) WHERE resolution = 'open';
