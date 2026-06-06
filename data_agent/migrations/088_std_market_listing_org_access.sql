-- 088: Organization-scoped visibility for standards market listings.

ALTER TABLE std_market_listing
    ADD COLUMN IF NOT EXISTS visibility_scope TEXT NOT NULL DEFAULT 'public';

ALTER TABLE std_market_listing
    ADD COLUMN IF NOT EXISTS owner_org_id TEXT;

ALTER TABLE std_market_listing
    ADD COLUMN IF NOT EXISTS allowed_org_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'std_market_listing_visibility_scope_check'
    ) THEN
        ALTER TABLE std_market_listing
            ADD CONSTRAINT std_market_listing_visibility_scope_check
            CHECK (visibility_scope IN ('public','organization','private'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_std_market_listing_visibility
    ON std_market_listing(visibility_scope);

CREATE INDEX IF NOT EXISTS idx_std_market_listing_owner_org
    ON std_market_listing(owner_org_id);

CREATE INDEX IF NOT EXISTS idx_std_market_listing_allowed_orgs
    ON std_market_listing USING GIN (allowed_org_ids);
