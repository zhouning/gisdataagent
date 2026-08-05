-- 134: Extend the ontology authority contract for the curated v2 model.

ALTER TABLE gda_ontology.concept
    DROP CONSTRAINT IF EXISTS ck_gda_ontology_concept_status;

ALTER TABLE gda_ontology.concept
    ADD CONSTRAINT ck_gda_ontology_concept_status CHECK (
        lifecycle_status IN (
            'candidate',
            'curated',
            'active',
            'deprecated',
            'rejected'
        )
    ) NOT VALID;

ALTER TABLE gda_ontology.concept
    VALIDATE CONSTRAINT ck_gda_ontology_concept_status;

ALTER TABLE gda_ontology.mapping
    DROP CONSTRAINT IF EXISTS ck_gda_ontology_mapping_type;

ALTER TABLE gda_ontology.mapping
    ADD CONSTRAINT ck_gda_ontology_mapping_type CHECK (
        mapping_type IN (
            'exact_match',
            'close_match',
            'broad_match',
            'narrow_match',
            'related_match',
            'denotes_class',
            'describes',
            'schema_correspondence'
        )
    ) NOT VALID;

ALTER TABLE gda_ontology.mapping
    VALIDATE CONSTRAINT ck_gda_ontology_mapping_type;
