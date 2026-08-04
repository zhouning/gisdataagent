-- 097: Add governed DolphinScheduler cancellation to the provider outbox.
--
-- Cancellation admission and its Run transition remain in one gateway
-- transaction. This migration only extends the immutable command vocabulary.

ALTER TABLE gda_control.platform_command_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_command_type;

ALTER TABLE gda_control.platform_command_outbox
    ADD CONSTRAINT ck_gda_command_type CHECK (
        command_type IN (
            'dolphinscheduler.dispatch',
            'dolphinscheduler.reconcile',
            'dolphinscheduler.cancel'
        )
    );
