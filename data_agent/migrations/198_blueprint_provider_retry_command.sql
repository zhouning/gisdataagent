-- 198: Add delayed Blueprint provider retries to the shared command outbox.
--
-- This extends the existing delivery vocabulary. PlatformRun remains the
-- lifecycle authority and available_at remains the database-enforced due gate.

ALTER TABLE gda_control.platform_command_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_command_type;
ALTER TABLE gda_control.platform_command_outbox
    ADD CONSTRAINT ck_gda_command_type CHECK (
        command_type IN (
            'dolphinscheduler.dispatch',
            'dolphinscheduler.reconcile',
            'dolphinscheduler.cancel',
            'metric_query.execute',
            'gis_analysis.execute',
            'gis_analysis.cancel',
            'gis_analysis.reconcile',
            'blueprint_provider.retry'
        )
    );
