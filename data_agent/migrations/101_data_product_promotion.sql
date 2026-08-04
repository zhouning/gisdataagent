-- 101: Audited activation of an already-published descendant version.

ALTER TABLE gda_control.data_product_event
    DROP CONSTRAINT ck_gda_data_product_event_type;

ALTER TABLE gda_control.data_product_event
    ADD CONSTRAINT ck_gda_data_product_event_type CHECK (
        event_type IN ('published', 'advanced', 'rolled_back', 'promoted')
    );
