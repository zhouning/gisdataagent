-- 144: Admit field-catalog attachments as governed ontology mapping evidence.

ALTER TABLE gda_ontology.ontology_source
    DROP CONSTRAINT IF EXISTS ck_gda_ontology_source_kind;

ALTER TABLE gda_ontology.ontology_source
    ADD CONSTRAINT ck_gda_ontology_source_kind CHECK (
        source_kind IN (
            'ea_repository',
            'standard_document',
            'controlled_vocabulary',
            'manual_governance',
            'curated_domain_ontology',
            'attachment_field_catalog'
        )
    ) NOT VALID;

ALTER TABLE gda_ontology.ontology_source
    VALIDATE CONSTRAINT ck_gda_ontology_source_kind;
