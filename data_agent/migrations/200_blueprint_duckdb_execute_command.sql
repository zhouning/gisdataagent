-- 200: Dispatch admitted DuckDB Blueprint tests through the shared outbox.
--
-- The outbox remains delivery state only. PlatformRun and migration 199 keep
-- lifecycle and success authority; this adds no scheduler or provider ledger.

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
            'blueprint_provider.execute',
            'blueprint_provider.retry'
        )
    );
