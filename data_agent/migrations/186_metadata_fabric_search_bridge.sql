-- 186: deterministic tenant-scoped Metadata Fabric crosswalk search bridge.
-- The index accelerates the authority-safe reference surface; provider
-- catalogs remain authoritative for metadata search and object reads.

CREATE INDEX IF NOT EXISTS idx_gda_metadata_binding_search
    ON gda_control.metadata_fabric_binding (
        tenant_id,
        system,
        resource_urn,
        external_namespace,
        external_object_type,
        external_object_id,
        binding_id
    );
