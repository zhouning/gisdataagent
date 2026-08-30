-- Bind a submitted business Decision Packet to the JQDLTB product release.

ALTER TABLE gda_control.jqdltb_data_product_release
    ADD COLUMN decision_packet_sha256 CHAR(64);

ALTER TABLE gda_control.jqdltb_data_product_release
    ADD CONSTRAINT chk_jqdltb_release_decision_packet_sha256
    CHECK (
        decision_packet_sha256 IS NULL
        OR decision_packet_sha256 ~ '^[0-9a-f]{64}$'
    );

CREATE OR REPLACE FUNCTION gda_control.require_jqdltb_decision_packet_release_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_release gda_control.jqdltb_data_product_release%ROWTYPE;
    v_release_case gda_control.approval_case%ROWTYPE;
    v_environment TEXT;
BEGIN
    IF NEW.mapping_contract->>'schema' IS DISTINCT FROM
            'gda.jqdltb_mapping_binding.v1' THEN
        RETURN NEW;
    END IF;

    SELECT * INTO v_release
      FROM gda_control.jqdltb_data_product_release
     WHERE tenant_id = NEW.tenant_id
       AND data_product_version_id = NEW.data_product_version_id;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    v_environment := v_release.operating_contract->>'environment';
    SELECT * INTO v_release_case
      FROM gda_control.approval_case
     WHERE tenant_id = NEW.tenant_id
       AND approval_case_ref = v_release.release_approval_case_ref;
    IF v_release.decision_packet_sha256 IS DISTINCT FROM
            NEW.mapping_contract->>'decision_packet_sha256'
       OR v_release.decision_packet_sha256 IS DISTINCT FROM
            NEW.distribution_manifest->>'decision_packet_sha256' THEN
        RAISE EXCEPTION 'JQDLTB Decision Packet binding differs from DataProductVersion'
            USING ERRCODE = '23514';
    END IF;
    IF v_release_case.request_context->>'decision_packet_sha256' IS DISTINCT FROM
            v_release.decision_packet_sha256 THEN
        RAISE EXCEPTION 'JQDLTB release ApprovalCase differs from Decision Packet binding'
            USING ERRCODE = '23514';
    END IF;
    IF v_environment IN ('staging', 'production')
       AND v_release.decision_packet_sha256 IS NULL THEN
        RAISE EXCEPTION 'staging and production JQDLTB releases require a Decision Packet'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_gda_jqdltb_decision_packet_release_binding
AFTER INSERT OR UPDATE ON gda_control.data_product_version
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION gda_control.require_jqdltb_decision_packet_release_binding();
